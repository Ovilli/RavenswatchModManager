using Stormancer;
using Stormancer.Core;
using Stormancer.Diagnostics;
using Stormancer.Server.Plugins.Configuration;
using Stormancer.Server.Plugins.Steam;
using Stormancer.Server.Plugins.Users;
using Stormancer.Server.Secrets;

namespace Rsmm.Backend;

/// <summary>
/// The stock Steam service, plus the two things this backend needs from the login path: it accepts
/// RSMM tickets in place of Steam ones, and it logs Steam's own reason when it rejects a real one.
/// </summary>
/// <remarks>
/// <para>
/// <b>Why the Steam channel.</b> Verifying a Steam ticket needs Passtech's publisher key, which we
/// will never have, so <c>AuthenticateUserTicket</c> always 403s here. But the game's client
/// already speaks the <c>steam</c> auth provider, and the only part of it we need to change is
/// which bytes it puts in the ticket field. So an RSMM ticket travels as if it were a Steam
/// ticket: this method recognises the <c>rsmm1.</c> prefix, verifies it against our own key, and
/// returns the SteamID64 the RSMM API already proved via Steam OpenID. The stock Steam provider
/// then creates the user and the session exactly as it would for a real ticket — no new auth
/// provider, no client protocol change.
/// </para>
/// <para>
/// A ticket without that prefix is still handed to Steam unchanged, so the day a publisher key
/// exists nothing here is in the way.
/// </para>
/// <para>
/// Every other member is delegated untouched. This class adds a second accepted credential and
/// some logging; it never makes Steam's own answer more permissive.
/// </para>
/// </remarks>
internal class RsmmSteamService : ISteamService
{
    private readonly Func<IEnumerable<ISteamService>> _all;
    private readonly ILogger _logger;
    private readonly IConfiguration _config;
    private readonly ISecretsStore _secrets;

    /// <summary>
    /// The verifier is static because it owns the replay cache. The container's lifetime for this
    /// service is the Steam plugin's to choose; if it ever became per-request, a per-instance cache
    /// would reset on every login and single-use tickets would silently stop being single-use.
    /// </summary>
    private static Task<RsmmTicketVerifier>? _verifier;
    private static readonly SemaphoreSlim VerifierLock = new(1, 1);

    /// <summary>Static for the same reason as the verifier: the container owns our lifetime.</summary>
    private static int _profileFailures;
    private static int _realProfileLogged;
    private static Task<string>? _steamApiKey;
    private static readonly SemaphoreSlim SteamKeyLock = new(1, 1);

    public RsmmSteamService(
        Func<IEnumerable<ISteamService>> all,
        ILogger logger,
        IConfiguration config,
        ISecretsStore secrets)
    {
        _all = all;
        _logger = logger;
        _config = config;
        _secrets = secrets;
    }

    private ISteamService Inner => _all().First(s => s is not RsmmSteamService);

    public async Task<(ulong steamId, uint appId)> AuthenticateUserTicket(string ticket, uint? appId, SteamAuthenticationProtocolVersion protocol)
    {
        var verifier = await GetVerifier();
        var options = ReadOptions();

        if (RsmmTicketVerifier.LooksLikeTicket(ticket))
        {
            var identity = verifier.Verify(ticket, out var error);
            if (identity is null)
            {
                // The reason goes to the log only. The client is told no more than "refused":
                // which check failed is exactly what a forger wants to know.
                _logger.Log(LogLevel.Warn, "rsmm.identity", "Refused an RSMM ticket", new { reason = error });
                throw new ClientException("authentication.refused");
            }

            ModPackRegistry.Verified(identity);
            _logger.Log(LogLevel.Info, "rsmm.identity", "Accepted an RSMM ticket", new
            {
                steamId = identity.SteamId,
                ownsGame = identity.OwnsGame,
                modPack = identity.Pack ?? "vanilla",
                packName = identity.PackName,
            });
            return (identity.SteamId, appId ?? SteamAppId(options));
        }

        if (TrustsUnverifiedTickets(options))
        {
            if (SteamTicket.TryReadSteamId(ticket, out var claimedId, out var why))
            {
                // Warn, every time, with the word "unvalidated" in it: this line is the only thing
                // standing between a test convenience and someone running it in front of players.
                _logger.Log(LogLevel.Warn, "rsmm.identity",
                    "TRUSTING AN UNVALIDATED STEAM TICKET — insecure, local testing only", new
                    {
                        steamId = claimedId,
                        trustUnverifiedSteamTickets = true,
                    });
                return (claimedId, appId ?? SteamAppId(options));
            }

            _logger.Log(LogLevel.Warn, "rsmm.identity",
                "Could not read a SteamID64 out of the ticket", new { reason = why });
            throw new ClientException("authentication.refused");
        }

        if (options.RequireVerifiedIdentity)
        {
            _logger.Log(LogLevel.Warn, "rsmm.identity", "Refused a login with no RSMM ticket", new
            {
                requireVerifiedIdentity = true,
                protocol = protocol.ToString(),
            });
            throw new ClientException("authentication.refused");
        }

        try
        {
            return await Inner.AuthenticateUserTicket(ticket, appId, protocol);
        }
        catch (Exception ex)
        {
            // The Steam plugin catches its own SteamException and reports only "Authentication
            // refused by steam." without ever logging Steam's text. This is the only place it survives.
            _logger.Log(LogLevel.Warn, "rsmm.steam", "Steam rejected a login ticket", new
            {
                reason = ex.Message,
                exception = ex.GetType().Name,
                appId,
                protocol = protocol.ToString(),
            });
            throw;
        }
    }

    private RsmmOptions ReadOptions() => _config.GetValue("rsmm", new RsmmOptions()) ?? new RsmmOptions();

    /// <summary>
    /// The insecure test path, from the config or from the environment. The environment is checked
    /// too so a local session never has to commit `trustUnverifiedSteamTickets: true` to the repo;
    /// the grid starts the app host as a child process, so its environment reaches us.
    /// </summary>
    private static bool TrustsUnverifiedTickets(RsmmOptions options)
    {
        if (options.TrustUnverifiedSteamTickets)
        {
            return true;
        }
        var env = Environment.GetEnvironmentVariable("RSMM_TRUST_UNVERIFIED_STEAM_TICKETS");
        return env is "1" or "true" or "TRUE";
    }

    private uint SteamAppId(RsmmOptions _) => _config.GetValue<uint>("steam.appId", 0);

    private async Task<RsmmTicketVerifier> GetVerifier()
    {
        if (_verifier is not null)
        {
            return await _verifier;
        }

        await VerifierLock.WaitAsync();
        try
        {
            _verifier ??= BuildVerifier();
            return await _verifier;
        }
        finally
        {
            VerifierLock.Release();
        }
    }

    private async Task<RsmmTicketVerifier> BuildVerifier()
    {
        var options = ReadOptions();
        var keys = new List<byte[]>();
        foreach (var path in options.TicketKeys)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                continue;
            }
            try
            {
                var secret = await _secrets.GetSecret(path);
                if (secret?.Value is { Length: > 0 } value)
                {
                    keys.Add(value);
                }
                else
                {
                    _logger.Log(LogLevel.Error, "rsmm.identity", "Ticket key is empty or missing", new { path });
                }
            }
            catch (Exception ex)
            {
                _logger.Log(LogLevel.Error, "rsmm.identity", "Could not read a ticket key", new { path, reason = ex.Message });
            }
        }

        await LogSteamKeyShape();

        // Logged at whatever level the outcome deserves: with no key, every RSMM ticket is refused,
        // which is the difference between "identity is on" and "identity is silently off".
        _logger.Log(keys.Count > 0 ? LogLevel.Info : LogLevel.Warn, "rsmm.identity", "RSMM identity configuration", new
        {
            ticketKeys = keys.Count,
            configuredPaths = options.TicketKeys.Length,
            options.RequireVerifiedIdentity,
            options.EnforceModPack,
            trustUnverifiedSteamTickets = TrustsUnverifiedTickets(options),
            options.MaxTicketAgeSeconds,
            options.ClockSkewSeconds,
        });

        return new RsmmTicketVerifier(keys, options);
    }

    /// <summary>
    /// The player's Steam profile, or a stand-in if Steam will not give us one.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Not a convenience: the stock <c>SteamAuthenticationProvider.Authenticate</c> calls this
    /// immediately after the ticket is accepted, so a failure here kills a login that had already
    /// succeeded — with a <c>403 (Forbidden)</c> from <c>ISteamUser/GetPlayerSummaries</c> that
    /// names nothing to do with authentication.
    /// </para>
    /// <para>
    /// It tries Steam and falls back, rather than checking first whether a key is configured.
    /// Presence is not validity: this grid HAS a secret at <c>steam.apiKey</c> and Steam rejects it,
    /// so a pre-check reported "key loaded" and then handed the login straight back to the 403 it
    /// was supposed to prevent. Only the call itself can say whether the key works, and the same
    /// fallback then also covers a revoked key, a rate limit and Steam being down.
    /// </para>
    /// <para>
    /// A profile is not needed for a correct login: it supplies a display name, and the RSMM ticket
    /// path does not depend on Steam for that at all — the mint side already knows who the player
    /// is. With a working free key (this endpoint needs no publisher key) real profiles come back
    /// through the untouched path.
    /// </para>
    /// </remarks>
    public async Task<SteamPlayerSummary?> GetPlayerSummary(ulong steamId) =>
        (await GetPlayerSummaries([steamId])).GetValueOrDefault(steamId);

    public async Task<Dictionary<ulong, SteamPlayerSummary>> GetPlayerSummaries(IEnumerable<ulong> steamIds)
    {
        var ids = steamIds.Distinct().ToList();

        // Ours first: the plugin sends this to partner.steam-api.com, where a free key is never
        // valid (see SteamProfiles).
        var apiKey = await GetSteamApiKey();
        if (!string.IsNullOrEmpty(apiKey))
        {
            try
            {
                var fetched = await SteamProfiles.FetchAsync(apiKey, ids);
                NoteRealProfiles(fetched.Count);
                // Steam omits accounts it will not talk about; fill those so a caller that indexes
                // the result does not throw on a private profile.
                foreach (var id in ids)
                {
                    fetched.TryAdd(id, Placeholder(id));
                }
                return fetched;
            }
            catch (Exception ex)
            {
                WarnAboutProfiles(ex);
            }
        }

        // The plugin's path, in case a publisher key is configured one day and the partner host is
        // the right place to ask after all.
        try
        {
            var summaries = await Inner.GetPlayerSummaries(ids);
            NoteRealProfiles(summaries.Count);
            return summaries;
        }
        catch (Exception ex)
        {
            WarnAboutProfiles(ex);
            return ids.ToDictionary(id => id, Placeholder);
        }
    }

    /// <summary>
    /// The Steam web API key from the grid's secret store, or empty when there is none.
    /// </summary>
    /// <remarks>
    /// Read here rather than through the plugin's <c>SteamKeyStore</c>, which only loads the key in
    /// its constructor from <c>configuration.Settings</c> and caches the result for the process.
    /// Cached the same way, since it cannot change without a redeploy.
    /// </remarks>
    private async Task<string> GetSteamApiKey()
    {
        if (_steamApiKey is not null)
        {
            return await _steamApiKey;
        }
        await SteamKeyLock.WaitAsync();
        try
        {
            _steamApiKey ??= ReadSteamApiKey();
            return await _steamApiKey;
        }
        finally
        {
            SteamKeyLock.Release();
        }
    }

    private async Task<string> ReadSteamApiKey()
    {
        var path = _config.GetValue<string?>("steam.apiKey", null);
        if (string.IsNullOrWhiteSpace(path))
        {
            return "";
        }
        try
        {
            var secret = await _secrets.GetSecret(path);
            return secret?.Value is { Length: > 0 } value
                ? System.Text.Encoding.UTF8.GetString(value).Trim()
                : "";
        }
        catch (Exception ex)
        {
            _logger.Log(LogLevel.Error, "rsmm.steam",
                "Could not read the steam.apiKey secret", new { path, reason = ex.Message });
            return "";
        }
    }

    /// <summary>
    /// Says so, once, when Steam actually answers.
    /// </summary>
    /// <remarks>
    /// Logging only the failure was not enough to debug this: the warning fired once per process, so
    /// its ABSENCE could mean either "the key started working" or "nothing asked again". A positive
    /// line makes success observable instead of inferred.
    /// </remarks>
    private void NoteRealProfiles(int count)
    {
        if (Interlocked.Exchange(ref _realProfileLogged, 1) == 0)
        {
            _logger.Log(LogLevel.Info, "rsmm.steam",
                "Steam returned real player profiles; the web API key works", new { count });
        }
    }

    /// <summary>
    /// A profile that names the account without claiming anything we did not verify. The persona is
    /// the account id, not a display name a player chose, so nobody mistakes it for a real one.
    /// </summary>
    private static SteamPlayerSummary Placeholder(ulong steamId) => new()
    {
        steamid = steamId,
        personaname = $"Player_{steamId & 0xFFFFFFFF}",
    };

    /// <summary>
    /// Every failure, with a running count.
    /// </summary>
    /// <remarks>
    /// Deliberately not once-per-process. A single line cannot be used to tell whether a later
    /// configuration change fixed the key, which is exactly the question that came up; one line per
    /// login is a price worth paying for an answer.
    /// </remarks>
    private void WarnAboutProfiles(Exception ex)
    {
        var failures = Interlocked.Increment(ref _profileFailures);
        _logger.Log(LogLevel.Warn, "rsmm.steam",
            "Steam would not return player profiles; using stand-in names. Logins are unaffected. "
                + "A FREE Steam web API key in steam.apiKey fixes it (this endpoint needs no "
                + "publisher key).",
            new { reason = ex.Message, exception = ex.GetType().Name, failures });
    }

    /// <summary>
    /// Reports the SHAPE of the configured Steam web API key — never its value.
    /// </summary>
    /// <remarks>
    /// A bad key is otherwise invisible. Steam answers <c>403</c> identically for a missing key, a
    /// wrong key and a correct key with a trailing newline, so the status says nothing about which,
    /// and the plugin that reads the key logs nothing at all. Length and "is it 32 hex characters"
    /// separate those cases without putting a credential in a log file.
    /// </remarks>
    private async Task LogSteamKeyShape()
    {
        var path = _config.GetValue<string?>("steam.apiKey", null);
        if (string.IsNullOrWhiteSpace(path))
        {
            _logger.Log(LogLevel.Info, "rsmm.steam", "No steam.apiKey configured", new { });
            return;
        }

        try
        {
            var secret = await _secrets.GetSecret(path);
            var value = secret?.Value;
            if (value is null || value.Length == 0)
            {
                _logger.Log(LogLevel.Warn, "rsmm.steam", "steam.apiKey secret is missing or empty", new { path });
                return;
            }

            var text = System.Text.Encoding.UTF8.GetString(value);
            var trimmed = text.Trim();
            // 32 hex characters is what Steam issues; anything else will 403 and look like a
            // permissions problem.
            var wellFormed = trimmed.Length == 32 && trimmed.All(Uri.IsHexDigit);
            _logger.Log(wellFormed ? LogLevel.Info : LogLevel.Warn, "rsmm.steam",
                wellFormed
                    ? "steam.apiKey looks well formed (32 hex characters)"
                    : "steam.apiKey is NOT 32 hex characters; Steam will answer 403",
                new
                {
                    path,
                    bytes = value.Length,
                    charsAfterTrim = trimmed.Length,
                    hadSurroundingWhitespace = trimmed.Length != text.Length,
                    allHex = trimmed.All(Uri.IsHexDigit),
                });
        }
        catch (Exception ex)
        {
            // The likeliest cause of a 403 we could not otherwise explain: the app cannot read the
            // store at all, so the plugin falls back to no key.
            _logger.Log(LogLevel.Error, "rsmm.steam",
                "Could not read the steam.apiKey secret — the Steam plugin will have no key either",
                new { path, reason = ex.Message, exception = ex.GetType().Name });
        }
    }

    public Task<SteamGetFriendsFromClientResult> GetFriendListFromClientAsync(ISceneHost scene, Session session, uint maxFriendsCount = uint.MaxValue, CancellationToken cancellationToken = default)
        => Inner.GetFriendListFromClientAsync(scene, session, maxFriendsCount, cancellationToken);

    public Task<SteamCreateLobbyData> CreateLobby(uint appId, string lobbyName, LobbyType lobbyType, int maxMembers, IEnumerable<ulong>? steamIdInvitedMembers = null, Dictionary<string, string>? lobbyMetadata = null)
        => Inner.CreateLobby(appId, lobbyName, lobbyType, maxMembers, steamIdInvitedMembers, lobbyMetadata);

    public Task RemoveUserFromLobby(uint appId, ulong steamIdToRemove, ulong steamIDLobby) => Inner.RemoveUserFromLobby(appId, steamIdToRemove, steamIDLobby);

    public Task<string> OpenVACSession(uint appId, string steamId) => Inner.OpenVACSession(appId, steamId);

    public Task CloseVACSession(uint appId, string steamId, string sessionId) => Inner.CloseVACSession(appId, steamId, sessionId);

    public Task<bool> RequestVACStatusForUser(uint appId, string steamId, string sessionId) => Inner.RequestVACStatusForUser(appId, steamId, sessionId);

    public Task<Dictionary<string, PartyDataDto>> DecodePartyDataBearerTokens(Dictionary<string, string> tokens) => Inner.DecodePartyDataBearerTokens(tokens);

    public Task<string> CreatePartyDataBearerToken(string partyId, string leaderUserId, ulong leaderSteamId) => Inner.CreatePartyDataBearerToken(partyId, leaderUserId, leaderSteamId);
}
