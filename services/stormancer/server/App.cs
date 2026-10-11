using Stormancer;
using Stormancer.Plugins;
using Stormancer.Server;
using Stormancer.Server.Plugins.GameFinder;
using Stormancer.Server.Plugins.GameSession;
using Stormancer.Server.Plugins.Party;
using Stormancer.Server.Plugins.Steam;
using Stormancer.Server.Plugins.Users;

namespace Rsmm.Backend;

/// <remarks>
/// Not named Run on purpose: the hosting source generator picks up every <c>Run(IAppBuilder)</c>
/// and registers ours first, ahead of the plugins, where the Steam plugin's own registration
/// would override ours. Program.cs adds this app last instead (see <see cref="RsmmSteamService"/>).
/// </remarks>
internal class App
{
    public void Register(IAppBuilder builder)
    {
        builder.AddPlugin(new RavenswatchPlugin());
    }
}

/// <summary>
/// The Ravenswatch backend: the scenes the game connects to under
/// <c>scene:/&lt;cluster&gt;/darktales/live-1-05-01/</c>.
/// </summary>
/// <remarks>
/// The plugins create the scene names the game expects on their own: Users → "authenticator",
/// Friends → "friends", Party → "party-manager" and "party-&lt;guid&gt;". Only the gamefinder
/// scene is declared here. Steam tickets are verified against Steam's web API, which needs the
/// <c>steam</c> config section (appId, backendIdentity, apiKey); see the README.
/// </remarks>
public class RavenswatchPlugin : IHostPlugin
{
    private const string GameFinder = "matchmaking";
    private const string GameSessionTemplate = "ravenswatch-run";

    public void Build(HostPluginBuildContext ctx)
    {
        ctx.HostDependenciesRegistration += (IDependencyBuilder builder) =>
        {
            builder.Register<PartyGuard>().As<IPartyEventHandler>().InstancePerRequest();
            // The Friends plugin needs a database; without one every party join failed. See InMemoryDatabase.
            builder.Register<InMemoryDatabase>().As<Stormancer.Server.Plugins.Database.EntityFrameworkCore.IDbContextLifecycleHandler>().SingleInstance();
            builder.Register<InMemoryJsonDocuments>().As<Stormancer.Server.Plugins.Database.EntityFrameworkCore.IDbModelBuilder>().SingleInstance();
            builder.Register<ModPackSessionHandler>().As<IUserSessionEventHandler>().InstancePerRequest();
            builder.Register<RunTrackerGameSessionHandler>().As<IGameSessionEventHandler>().InstancePerRequest();
            builder.Register(static r => new RsmmSteamService(r.Resolve<Func<IEnumerable<ISteamService>>>(), r.Resolve<Stormancer.Diagnostics.ILogger>(), r.Resolve<Stormancer.Server.Plugins.Configuration.IConfiguration>(), r.Resolve<Stormancer.Server.Secrets.ISecretsStore>())).As<ISteamService>();
        };

        ctx.HostStarting += (IHost host) =>
        {
            // Steam stays enabled (it is what the client prefers), but without Passtech's
            // publisher key its ticket validation always 403s. RsmmSteamService therefore accepts
            // an RSMM ticket — minted by our API after a Steam OpenID login, which needs no
            // publisher key — in the ticket field instead, and only falls through to Steam for a
            // ticket that is not one of ours.
            //
            // The first-party `ephemeral` and `deviceidentifier` providers stay enabled, but NOT as
            // a fallback for the game: observed 2026-10-04, the client tries `steam` only and
            // disconnects when it is refused ("Login failed : Authentication refused by steam."),
            // with no second attempt. So the anonymous tier is unreachable from Ravenswatch itself
            // and the ticket path is the only way a real client gets in — not an optimisation.
            // They stay on for clients we write (tools, a lobby browser), which can choose them.
            host.ConfigureUsers(u => u
                .ConfigureSteam(s => s.Enabled().DefaultAuthProtocol(SteamAuthenticationProtocolVersion.V1))
                .ConfigureEphemeral(b => b.Enabled())
                .ConfigureDeviceIdentifier(b => b.Enabled()));

            // Ravenswatch launches runs from a party: the party leader hosts the P2P session.
            host.ConfigureGamefinderTemplate(GameFinder, c => c
                .ConfigurePartyGameFinder(o => o
                    .PartyLeaderIsHost(true)
                    .GameSessionTemplate(GameSessionTemplate)));

            host.ConfigureGameSession(GameSessionTemplate, c => c);
        };

        ctx.HostStarted += (IHost host) =>
        {
            host.AddGamefinder(GameFinder, GameFinder);
        };
    }
}
