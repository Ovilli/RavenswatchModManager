using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Rsmm.Backend.Tests;

/// <summary>
/// Mints tickets the way the RSMM API does, so the verifier is tested against the real format
/// rather than against itself.
/// </summary>
/// <remarks>
/// This is the reference the TypeScript minter has to agree with. <c>TicketVectorTests</c> pins the
/// byte-level format so a change on either side shows up as a failing test instead of as a login
/// that refuses every player.
/// </remarks>
internal static class TicketMint
{
    internal static byte[] Key(string material) => Encoding.UTF8.GetBytes(material);

    internal static string Sign(byte[] key, string payloadJson)
    {
        var payload = Base64Url(Encoding.UTF8.GetBytes(payloadJson));
        var signed = $"{RsmmTicketVerifier.Prefix}.{payload}";
        var signature = Base64Url(HMACSHA256.HashData(key, Encoding.ASCII.GetBytes(signed)));
        return $"{signed}.{signature}";
    }

    internal static string Mint(
        byte[] key,
        ulong steamId = 76561197960287930UL,
        bool ownsGame = true,
        string? pack = "a1b2c3d4e5f60718",
        string? packName = "Test pack",
        long? issuedAt = null,
        long? expires = null,
        string? jti = null)
    {
        var now = issuedAt ?? DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var payload = new Dictionary<string, object?>
        {
            ["sid"] = steamId.ToString(),
            ["own"] = ownsGame,
            ["pack"] = pack,
            ["packName"] = packName,
            ["iat"] = now,
            ["exp"] = expires ?? now + 300,
            ["jti"] = jti ?? Guid.NewGuid().ToString("N"),
        };
        return Sign(key, JsonSerializer.Serialize(payload));
    }

    internal static string Base64Url(byte[] bytes) =>
        Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
}
