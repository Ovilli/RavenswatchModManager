using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Rsmm.Backend;

/// <summary>
/// The <c>rsmm</c> config section. Logged at startup (see <see cref="RsmmSteamService"/>) so a
/// mistyped path shows up as zeroes in grid.log rather than as a silent accept-everything.
/// </summary>
public class RsmmOptions
{
    /// <summary>
    /// Secret-store paths holding the ticket signing keys, e.g. <c>darktales/rsmm/ticketKey</c>.
    /// More than one so a key can be rotated: a ticket is accepted if ANY of them verifies it,
    /// which lets the new key be deployed before the mint side switches over.
    /// </summary>
    public string[] TicketKeys { get; set; } = [];

    /// <summary>
    /// Refuse logins that do not carry a valid RSMM ticket. Off by default: with it on, and no
    /// loader able to supply a ticket yet, nobody can log in at all.
    /// </summary>
    public bool RequireVerifiedIdentity { get; set; }

    /// <summary>Refuse party joins whose mod pack differs from the party's.</summary>
    public bool EnforceModPack { get; set; } = true;

    /// <summary>
    /// How long a minted ticket stays usable. Short, because the only replay protection that
    /// survives a grid restart is this window.
    /// </summary>
    public int MaxTicketAgeSeconds { get; set; } = 600;

    /// <summary>Tolerance for a mint-side clock that disagrees with ours.</summary>
    public int ClockSkewSeconds { get; set; } = 60;
}

/// <summary>A verified RSMM identity: who the player is, and which mods they are running.</summary>
/// <param name="SteamId">SteamID64, proven by the mint side via Steam OpenID, not by the client.</param>
/// <param name="OwnsGame">
/// Whether the mint side could see appid 2071280 in this account's library. False means "could not
/// tell" as often as it means "does not own" — a private profile hides the library from Steam's
/// public web API — so this is a badge, never a gate.
/// </param>
/// <param name="Pack">Mod-pack fingerprint, or null for an unmodded game.</param>
/// <param name="PackName">Human-readable pack name, for log lines only.</param>
public sealed record RsmmIdentity(ulong SteamId, bool OwnsGame, string? Pack, string? PackName);

/// <summary>
/// Verifies the signed tickets the RSMM API mints after a Steam OpenID login.
/// </summary>
/// <remarks>
/// <para>
/// Format: <c>rsmm1.&lt;payload&gt;.&lt;signature&gt;</c>, both parts base64url, signature =
/// HMAC-SHA256 over the ASCII bytes of <c>"rsmm1." + payload</c>.
/// </para>
/// <para>
/// HMAC rather than a signature scheme on purpose: the grid holds the same key the minter does, so
/// a compromised grid can mint identities. The alternative (Ed25519, grid holds only a public key)
/// is better and is the upgrade path, but .NET 8 has no in-box Ed25519 and adding BouncyCastle to
/// this project risks the dependency-pin breakage documented in RsmmBackend.csproj. Revisit when
/// the grid is deployed somewhere we do not control.
/// </para>
/// <para>
/// Nothing here trusts the game client. The client only carries the ticket; every field in it was
/// decided by the API after it verified the Steam login server-side.
/// </para>
/// </remarks>
public sealed class RsmmTicketVerifier
{
    /// <summary>Ticket prefix, also the format version. A v2 would be a different prefix.</summary>
    public const string Prefix = "rsmm1";

    /// <summary>
    /// The lowest possible SteamID64 (individual account, universe 1). Anything below it is not a
    /// Steam account id, so a ticket carrying one is malformed rather than merely unknown.
    /// </summary>
    private const ulong MinSteamId64 = 76561197960265728UL;

    private readonly byte[][] _keys;
    private readonly RsmmOptions _options;
    private readonly ConcurrentDictionary<string, long> _usedJti = new();

    public RsmmTicketVerifier(IEnumerable<byte[]> keys, RsmmOptions options)
    {
        _keys = keys.Where(k => k.Length > 0).ToArray();
        _options = options;
    }

    /// <summary>True when any signing key is configured; false means every ticket is rejected.</summary>
    public bool Enabled => _keys.Length > 0;

    /// <summary>Whether <paramref name="candidate"/> is shaped like an RSMM ticket.</summary>
    /// <remarks>
    /// Used to tell our tickets apart from real Steam ones without trying to verify, so a genuine
    /// Steam ticket still reaches Steam when a publisher key is available.
    /// </remarks>
    public static bool LooksLikeTicket(string? candidate) =>
        candidate is not null && candidate.StartsWith(Prefix + ".", StringComparison.Ordinal);

    /// <summary>
    /// Verifies a ticket. Returns null and sets <paramref name="error"/> on every failure; the
    /// error text is for logs, never for the client (it would tell an attacker which check failed).
    /// </summary>
    public RsmmIdentity? Verify(string ticket, out string error)
    {
        error = "";
        if (!Enabled)
        {
            error = "no ticket key configured";
            return null;
        }

        var parts = ticket.Split('.');
        if (parts.Length != 3 || parts[0] != Prefix)
        {
            error = "malformed ticket";
            return null;
        }

        var signed = Encoding.ASCII.GetBytes($"{parts[0]}.{parts[1]}");
        if (!TryDecode(parts[2], out var signature))
        {
            error = "malformed signature";
            return null;
        }

        if (!VerifySignature(signed, signature))
        {
            error = "bad signature";
            return null;
        }

        if (!TryDecode(parts[1], out var payloadBytes))
        {
            error = "malformed payload";
            return null;
        }

        RsmmTicketPayload? payload;
        try
        {
            payload = JsonSerializer.Deserialize<RsmmTicketPayload>(payloadBytes);
        }
        catch (JsonException ex)
        {
            error = $"unreadable payload: {ex.Message}";
            return null;
        }

        if (payload is null)
        {
            error = "empty payload";
            return null;
        }

        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        // long, not int: the two configured windows are added together below, and at int width a
        // large pair of values wraps negative and rejects every ticket as "too old".
        long skew = _options.ClockSkewSeconds;
        long maxAge = _options.MaxTicketAgeSeconds;

        if (payload.Expires <= 0 || payload.IssuedAt <= 0)
        {
            error = "ticket has no validity window";
            return null;
        }

        if (now > payload.Expires + skew)
        {
            error = "ticket expired";
            return null;
        }

        if (payload.IssuedAt > now + skew)
        {
            error = "ticket issued in the future";
            return null;
        }

        if (now - payload.IssuedAt > maxAge + skew)
        {
            error = "ticket older than the configured maximum age";
            return null;
        }

        if (!ulong.TryParse(payload.SteamId, out var steamId) || steamId < MinSteamId64)
        {
            error = "payload carries no usable SteamID64";
            return null;
        }

        if (string.IsNullOrEmpty(payload.Jti))
        {
            error = "ticket has no id";
            return null;
        }

        // Replay: a ticket is single-use. The window only has to cover MaxTicketAgeSeconds,
        // because an older ticket is rejected above whether or not it is remembered here.
        PruneUsedJti(now);
        if (!_usedJti.TryAdd(payload.Jti, payload.Expires + skew))
        {
            error = "ticket already used";
            return null;
        }

        return new RsmmIdentity(steamId, payload.OwnsGame, NullIfBlank(payload.Pack), NullIfBlank(payload.PackName));
    }

    private bool VerifySignature(byte[] signed, byte[] signature)
    {
        // Every key is tried even after one matches: a short-circuit would make the number of
        // configured keys observable through response timing.
        var matched = false;
        foreach (var key in _keys)
        {
            var expected = HMACSHA256.HashData(key, signed);
            if (CryptographicOperations.FixedTimeEquals(expected, signature))
            {
                matched = true;
            }
        }
        return matched;
    }

    private void PruneUsedJti(long now)
    {
        foreach (var (jti, expiry) in _usedJti)
        {
            if (expiry < now)
            {
                _usedJti.TryRemove(jti, out _);
            }
        }
    }

    private static string? NullIfBlank(string? value) => string.IsNullOrWhiteSpace(value) ? null : value;

    /// <summary>base64url without padding, the form the API mints.</summary>
    private static bool TryDecode(string value, out byte[] bytes)
    {
        var padded = value.Replace('-', '+').Replace('_', '/');
        // length % 4 == 1 is not a truncated base64 string, it is an impossible one: reject it
        // rather than padding it into something Convert will accept.
        switch (padded.Length % 4)
        {
            case 1: bytes = []; return false;
            case 2: padded += "=="; break;
            case 3: padded += "="; break;
        }
        try
        {
            bytes = Convert.FromBase64String(padded);
            return true;
        }
        catch (FormatException)
        {
            bytes = [];
            return false;
        }
    }

    private sealed class RsmmTicketPayload
    {
        [JsonPropertyName("sid")] public string SteamId { get; set; } = "";
        [JsonPropertyName("own")] public bool OwnsGame { get; set; }
        [JsonPropertyName("pack")] public string? Pack { get; set; }
        [JsonPropertyName("packName")] public string? PackName { get; set; }
        [JsonPropertyName("iat")] public long IssuedAt { get; set; }
        [JsonPropertyName("exp")] public long Expires { get; set; }
        [JsonPropertyName("jti")] public string Jti { get; set; } = "";
    }
}
