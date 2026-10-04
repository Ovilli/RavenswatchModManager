using Stormancer.Diagnostics;
using Stormancer.Server.Plugins.Configuration;
using Stormancer.Server.Plugins.Party;
using Stormancer.Server.Plugins.Party.Model;

namespace Rsmm.Backend;

/// <summary>
/// Party rules for Ravenswatch: 4 players, no joining a party whose run has started, and no mixing
/// mod packs.
/// </summary>
/// <remarks>
/// <para>
/// On Passtech's backend the party and its 6-digit code stay open for the whole run, so a late
/// joiner lands in the party and the voice room (keyed by the same code) but never in the game.
/// Two signals mark a run as started, because it is not yet known which one Ravenswatch produces:
/// a member inside a started Stormancer game session (<see cref="RunTracker"/>), or every member
/// marked Ready (the game logs "Party State | Ready" when the host launches). The log line names
/// the signal that fired, so the first real session shows which one to keep.
/// </para>
/// <para>
/// The mod-pack rule is the reason to run this backend at all for a modded game: Ravenswatch is
/// host-authoritative P2P over a shared asset set, so a party whose members applied different mods
/// is a party that desyncs. Passtech's backend cannot know about mods; ours does, because the pack
/// fingerprint rides in the login ticket the mod manager minted (<see cref="ModPackRegistry"/>).
/// </para>
/// <para>
/// It fails open: a member whose pack is unknown — an unverified login, or a player who connected
/// before this was deployed — is never refused, because "unknown" and "different" are not the same
/// thing and refusing on unknown would empty every party during a rollout.
/// </para>
/// </remarks>
public class PartyGuard : IPartyEventHandler
{
    private const int MaxMembers = 4;
    private readonly ILogger _logger;
    private readonly IConfiguration _config;

    public PartyGuard(ILogger logger, IConfiguration config)
    {
        _logger = logger;
        _config = config;
    }

    public Task OnCreatingParty(PartyCreationContext ctx)
    {
        ctx.MaxMembers(MaxMembers);
        _logger.Log(LogLevel.Info, "rsmm.party", "Creating party", new
        {
            gameFinder = ctx.PartyRequest.GameFinderName,
            isJoinable = ctx.PartyRequest.IsJoinable,
            customData = ctx.PartyRequest.CustomData,
        });
        return Task.CompletedTask;
    }

    public Task OnJoining(JoiningPartyContext ctx)
    {
        var members = ctx.Party.State.PartyMembers.Values.ToList();
        var inRun = members.Any(m => RunTracker.IsInRun(m.UserId));
        var allReady = members.Count > 0 && members.All(m => m.StatusInParty == PartyMemberStatus.Ready);

        if (inRun || allReady)
        {
            ctx.Accept = false;
            ctx.Reason = "party.runInProgress";
            _logger.Log(LogLevel.Info, "rsmm.party", "Refused join: run in progress", new
            {
                party = ctx.Party.Settings.PartyId,
                signal = inRun ? "gameSession" : "allReady",
                joiningUser = ctx.Session.User?.Id,
            });
            return Task.CompletedTask;
        }

        RefuseOnModPackMismatch(ctx, members);
        return Task.CompletedTask;
    }

    /// <summary>
    /// Refuses a join when the joining player's mod pack differs from one already in the party.
    /// </summary>
    private void RefuseOnModPackMismatch(JoiningPartyContext ctx, List<PartyMember> members)
    {
        var options = _config.GetValue("rsmm", new RsmmOptions()) ?? new RsmmOptions();
        if (!options.EnforceModPack)
        {
            return;
        }

        var joiningUserId = ctx.Session.User?.Id;
        var joining = joiningUserId is null ? null : ModPackRegistry.ForUser(joiningUserId);
        if (joining is null)
        {
            return;
        }

        foreach (var member in members)
        {
            var seated = ModPackRegistry.ForUser(member.UserId);
            if (seated is null || seated.Pack == joining.Pack)
            {
                continue;
            }

            ctx.Accept = false;
            ctx.Reason = "party.modPackMismatch";
            _logger.Log(LogLevel.Info, "rsmm.party", "Refused join: mod pack mismatch", new
            {
                party = ctx.Party.Settings.PartyId,
                joiningUser = joiningUserId,
                joiningPack = joining.Label,
                partyMember = member.UserId,
                partyPack = seated.Label,
            });
            return;
        }
    }

    public Task OnUpdateSettings(PartySettingsUpdateCtx ctx)
    {
        _logger.Log(LogLevel.Info, "rsmm.party", "Party settings updated", new
        {
            party = ctx.Party.Settings.PartyId,
            gameFinder = ctx.Config.GameFinderName,
            isJoinable = ctx.Config.IsJoinable,
            customData = ctx.Config.CustomData,
        });
        return Task.CompletedTask;
    }

    public Task OnPlayerReadyStateChanged(PlayerReadyStateContext ctx)
    {
        _logger.Log(LogLevel.Info, "rsmm.party", "Ready state changed", new
        {
            party = ctx.Party.Settings.PartyId,
            members = ctx.Party.State.PartyMembers.Values.Select(m => new { m.UserId, status = m.StatusInParty.ToString() }),
        });
        return Task.CompletedTask;
    }
}
