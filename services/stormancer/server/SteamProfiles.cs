using System.Net.Http.Json;
using System.Text.Json.Serialization;
using Stormancer.Server.Plugins.Steam;

namespace Rsmm.Backend;

/// <summary>
/// Fetches Steam player profiles from Steam's <b>public</b> web API.
/// </summary>
/// <remarks>
/// <para>
/// The Steam plugin cannot do this with the key we have. It sends every Steam web API call to
/// <c>https://partner.steam-api.com</c> — a <c>private const</c>, so no configuration reaches it —
/// and that host only accepts a <b>publisher</b> key. A perfectly good free key gets <c>403</c>
/// there and <c>200</c> on <c>api.steampowered.com</c>; both were measured.
/// </para>
/// <para>
/// Its own fallback does not help: <c>TryGetAsync</c> retries on the public host only when the
/// request throws <c>HttpRequestException</c>, i.e. a network failure. A 403 is a successful HTTP
/// exchange, so the retry never runs and the caller's <c>EnsureSuccessStatusCode()</c> throws.
/// </para>
/// <para>
/// So this issues the request itself, against the public host, with the key read from the grid's
/// secret store. <c>GetPlayerSummaries</c> is a public endpoint — it has never needed a publisher
/// key, unlike ticket validation, which stays impossible.
/// </para>
/// </remarks>
internal static class SteamProfiles
{
    /// <summary>The host a free key is valid on.</summary>
    private const string PublicApiRoot = "https://api.steampowered.com";

    /// <summary>Steam's documented maximum ids per GetPlayerSummaries call.</summary>
    private const int BatchSize = 100;

    /// <summary>One client for the process, as recommended for HttpClient.</summary>
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(10) };

    /// <summary>
    /// Profiles for the given ids. Ids Steam does not return (private or deleted accounts) are
    /// simply absent from the result, which is what the caller expects.
    /// </summary>
    /// <exception cref="HttpRequestException">The request failed; the caller decides what to do.</exception>
    internal static async Task<Dictionary<ulong, SteamPlayerSummary>> FetchAsync(
        string apiKey,
        IEnumerable<ulong> steamIds,
        CancellationToken ct = default)
    {
        var result = new Dictionary<ulong, SteamPlayerSummary>();
        var ids = steamIds.Distinct().ToList();

        for (var offset = 0; offset < ids.Count; offset += BatchSize)
        {
            var batch = ids.Skip(offset).Take(BatchSize);
            var url = $"{PublicApiRoot}/ISteamUser/GetPlayerSummaries/v0002/"
                + $"?key={Uri.EscapeDataString(apiKey)}&steamids={string.Join(',', batch)}";

            var envelope = await Http.GetFromJsonAsync<Envelope>(url, ct);
            foreach (var player in envelope?.response?.players ?? [])
            {
                // Steam sends steamid as a STRING; the plugin's model types it as ulong.
                if (player.steamid is null || !ulong.TryParse(player.steamid, out var steamId))
                {
                    continue;
                }
                result[steamId] = new SteamPlayerSummary
                {
                    steamid = steamId,
                    personaname = player.personaname,
                    profileurl = player.profileurl,
                    avatar = player.avatar,
                    avatarmedium = player.avatarmedium,
                    avatarfull = player.avatarfull,
                    communityvisibilitystate = player.communityvisibilitystate,
                    personastate = player.personastate,
                    profilestate = player.profilestate,
                    realname = player.realname,
                    loccountrycode = player.loccountrycode,
                    locstatecode = player.locstatecode,
                    lastlogoff = player.lastlogoff,
                };
            }
        }

        return result;
    }

    private sealed class Envelope
    {
        [JsonPropertyName("response")] public PlayerList? response { get; set; }
    }

    private sealed class PlayerList
    {
        [JsonPropertyName("players")] public List<Player>? players { get; set; }
    }

    /// <summary>Only the fields the plugin's model carries; Steam sends more.</summary>
    private sealed class Player
    {
        [JsonPropertyName("steamid")] public string? steamid { get; set; }
        [JsonPropertyName("personaname")] public string? personaname { get; set; }
        [JsonPropertyName("profileurl")] public string? profileurl { get; set; }
        [JsonPropertyName("avatar")] public string? avatar { get; set; }
        [JsonPropertyName("avatarmedium")] public string? avatarmedium { get; set; }
        [JsonPropertyName("avatarfull")] public string? avatarfull { get; set; }
        [JsonPropertyName("communityvisibilitystate")] public int communityvisibilitystate { get; set; }
        [JsonPropertyName("personastate")] public int personastate { get; set; }
        [JsonPropertyName("profilestate")] public int profilestate { get; set; }
        [JsonPropertyName("realname")] public string? realname { get; set; }
        [JsonPropertyName("loccountrycode")] public string? loccountrycode { get; set; }
        [JsonPropertyName("locstatecode")] public string? locstatecode { get; set; }
        [JsonPropertyName("lastlogoff")] public int lastlogoff { get; set; }
    }
}
