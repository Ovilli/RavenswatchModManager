using System.Collections.Concurrent;
using Stormancer.Diagnostics;
using Stormancer.Server.Plugins.Users;

namespace Rsmm.Backend;

/// <summary>What a connected player is running: their verified identity and their mod pack.</summary>
public sealed record PlayerPack(ulong SteamId, bool OwnsGame, string? Pack, string? PackName)
{
    /// <summary>A pack fingerprint for logs and refusal reasons; "vanilla" when there is none.</summary>
    public string Label => Pack is null ? "vanilla" : PackName is null ? Pack : $"{PackName} ({Pack})";
}

/// <summary>
/// Which mod pack each connected player has applied, so party joins can be matched on it.
/// </summary>
/// <remarks>
/// <para>
/// Two stages, because the mod pack arrives at a different moment than the user id does. The
/// ticket is verified during authentication (<see cref="RsmmSteamService"/>), which knows the
/// SteamID64 but not yet the Stormancer user id; the user id only exists once login completes, at
/// <see cref="ModPackSessionHandler.OnLoggedIn"/>, which is where the entry is re-keyed. A party
/// handler then has the cheap <see cref="ForUser"/> lookup it needs, with no session round-trip.
/// </para>
/// <para>
/// Process-wide, exactly like <see cref="RunTracker"/>: correct on a single-node grid, where the
/// authenticator and party scenes share a process. A multi-node grid would need this in the
/// cluster's distributed cache.
/// </para>
/// </remarks>
public static class ModPackRegistry
{
    private static readonly ConcurrentDictionary<ulong, PlayerPack> BySteamId = new();
    private static readonly ConcurrentDictionary<string, PlayerPack> ByUserId = new();

    /// <summary>Records a freshly verified ticket, before the user id is known.</summary>
    internal static void Verified(RsmmIdentity identity) =>
        BySteamId[identity.SteamId] = new PlayerPack(identity.SteamId, identity.OwnsGame, identity.Pack, identity.PackName);

    /// <summary>Re-keys a verified ticket onto the Stormancer user id once login has produced one.</summary>
    /// <returns>The pack, or null when this login carried no RSMM ticket.</returns>
    internal static PlayerPack? Bind(string userId, ulong steamId)
    {
        if (!BySteamId.TryRemove(steamId, out var pack))
        {
            return null;
        }
        ByUserId[userId] = pack;
        return pack;
    }

    /// <summary>The pack of a connected player, or null when they never presented a ticket.</summary>
    public static PlayerPack? ForUser(string userId) => ByUserId.GetValueOrDefault(userId);

    internal static void Remove(string userId) => ByUserId.TryRemove(userId, out _);

    /// <summary>
    /// Drops an entry that was verified but never bound — a ticket accepted by a login that then
    /// failed. Without this, an abandoned authentication would pin the pack until the next one.
    /// </summary>
    internal static void Forget(ulong steamId) => BySteamId.TryRemove(steamId, out _);
}

/// <summary>Moves a verified ticket's pack onto the user id at login, and clears it at logout.</summary>
public class ModPackSessionHandler : IUserSessionEventHandler
{
    private readonly ILogger _logger;

    public ModPackSessionHandler(ILogger logger)
    {
        _logger = logger;
    }

    public Task OnLoggedIn(LoginContext ctx)
    {
        var userId = ctx.AuthenticatedUser?.Id;
        var platformUserId = ctx.Session?.platformId.PlatformUserId;
        if (userId is null || !ulong.TryParse(platformUserId, out var steamId))
        {
            return Task.CompletedTask;
        }

        var pack = ModPackRegistry.Bind(userId, steamId);
        _logger.Log(LogLevel.Info, "rsmm.identity", "Player logged in", new
        {
            userId,
            steamId,
            verified = pack is not null,
            ownsGame = pack?.OwnsGame,
            modPack = pack?.Label ?? "unverified",
        });
        return Task.CompletedTask;
    }

    public Task OnLoggedOut(LogoutContext ctx)
    {
        var userId = ctx.Session?.User?.Id;
        if (userId is not null)
        {
            ModPackRegistry.Remove(userId);
        }
        return Task.CompletedTask;
    }

    public Task OnKicking(KickContext ctx) => Task.CompletedTask;
}
