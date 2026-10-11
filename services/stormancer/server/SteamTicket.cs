using System.Buffers.Binary;

namespace Rsmm.Backend;

/// <summary>
/// Reads the SteamID64 out of a Steam web-API ticket <b>without validating it</b>.
/// </summary>
/// <remarks>
/// <para>
/// <b>This is not authentication.</b> A ticket's signature can only be checked by Steam, through
/// <c>ISteamUserAuth/AuthenticateUserTicket</c> and a publisher key for the app id. Everything here
/// reads attacker-controllable bytes: anyone who can reach the authenticator can hand us a
/// hand-written blob with any SteamID64 in it and be believed. It exists so a local grid can be
/// driven by a real game client while the real path (a signed RSMM ticket, see
/// <see cref="RsmmTicketVerifier"/>) is still being built, and it is reachable only behind
/// <see cref="RsmmOptions.TrustUnverifiedSteamTickets"/>, which defaults to off.
/// </para>
/// <para>
/// The id is found by structure rather than at a fixed offset. A Steam app ticket does carry the
/// SteamID64 at offset 12, but that depends on the section layout in front of it, and a wrong guess
/// would silently yield a plausible-looking wrong account. Instead every 8-byte little-endian
/// window is tested against the shape of an individual account id (universe 1, account type 1), the
/// offset-12 reading wins when several windows match, and an ambiguous ticket is refused.
/// </para>
/// </remarks>
internal static class SteamTicket
{
    /// <summary>Where a Steam app ticket's SteamID64 sits when the leading GC-token section is 20 bytes.</summary>
    private const int ConventionalOffset = 12;

    /// <summary>Universe 1 ("public") and account type 1 ("individual"): a real player's id.</summary>
    private const ulong PublicUniverse = 1;
    private const ulong IndividualAccount = 1;

    /// <summary>The lowest possible individual SteamID64.</summary>
    private const ulong MinSteamId64 = 76561197960265728UL;

    /// <summary>
    /// Finds the single plausible SteamID64 in a ticket, or returns false and says why.
    /// </summary>
    internal static bool TryReadSteamId(string? ticket, out ulong steamId, out string error)
    {
        steamId = 0;
        error = "";

        if (string.IsNullOrWhiteSpace(ticket))
        {
            error = "empty ticket";
            return false;
        }

        if (!TryDecode(ticket, out var bytes))
        {
            error = "ticket is neither hex nor base64";
            return false;
        }

        if (bytes.Length < sizeof(ulong))
        {
            error = $"ticket is only {bytes.Length} bytes";
            return false;
        }

        var found = new List<(int offset, ulong id)>();
        for (var i = 0; i + sizeof(ulong) <= bytes.Length; i++)
        {
            var candidate = BinaryPrimitives.ReadUInt64LittleEndian(bytes.AsSpan(i, sizeof(ulong)));
            if (IsIndividualSteamId(candidate))
            {
                found.Add((i, candidate));
            }
        }

        var distinct = found.Select(f => f.id).Distinct().ToList();
        if (distinct.Count == 0)
        {
            error = $"no SteamID64 found in {bytes.Length} bytes";
            return false;
        }

        if (distinct.Count > 1)
        {
            // Prefer the conventional position before giving up: several ids in one ticket is
            // normal enough (a ticket can name more than one party) that refusing outright would
            // be unhelpful, but picking an arbitrary one would be a silent wrong answer.
            var conventional = found.FirstOrDefault(f => f.offset == ConventionalOffset);
            if (conventional.id == 0)
            {
                error = $"ambiguous: {distinct.Count} candidate ids and none at offset {ConventionalOffset}";
                return false;
            }
            steamId = conventional.id;
            return true;
        }

        steamId = distinct[0];
        return true;
    }

    /// <summary>Whether a 64-bit value has the shape of an individual account's SteamID64.</summary>
    private static bool IsIndividualSteamId(ulong value) =>
        value >= MinSteamId64
        && (value >> 56) == PublicUniverse
        && ((value >> 52) & 0xF) == IndividualAccount;

    /// <summary>
    /// Steam web-API tickets are conventionally sent as hex; base64 is accepted too because which
    /// of the two a client picks is its own business and guessing wrong would look like a bad ticket.
    /// </summary>
    private static bool TryDecode(string ticket, out byte[] bytes)
    {
        var trimmed = ticket.Trim();
        if (trimmed.Length % 2 == 0 && trimmed.All(Uri.IsHexDigit))
        {
            bytes = Convert.FromHexString(trimmed);
            return true;
        }

        try
        {
            bytes = Convert.FromBase64String(trimmed);
            return true;
        }
        catch (FormatException)
        {
            bytes = [];
            return false;
        }
    }
}
