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

        // Logged at whatever level the outcome deserves: with no key, every RSMM ticket is refused,
        // which is the difference between "identity is on" and "identity is silently off".
        _logger.Log(keys.Count > 0 ? LogLevel.Info : LogLevel.Warn, "rsmm.identity", "RSMM identity configuration", new
        {
            ticketKeys = keys.Count,
            configuredPaths = options.TicketKeys.Length,
            options.RequireVerifiedIdentity,
            options.EnforceModPack,
            options.MaxTicketAgeSeconds,
            options.ClockSkewSeconds,
        });

        return new RsmmTicketVerifier(keys, options);
    }

    public Task<SteamPlayerSummary?> GetPlayerSummary(ulong steamId) => Inner.GetPlayerSummary(steamId);

    public Task<Dictionary<ulong, SteamPlayerSummary>> GetPlayerSummaries(IEnumerable<ulong> steamIds) => Inner.GetPlayerSummaries(steamIds);

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
