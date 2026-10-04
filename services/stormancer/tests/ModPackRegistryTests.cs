using Xunit;

namespace Rsmm.Backend.Tests;

/// <summary>
/// The two-stage handover from "ticket verified" to "party member with a known mod pack".
/// </summary>
/// <remarks>
/// Each test uses its own SteamID64 and user id: <see cref="ModPackRegistry"/> is process-wide
/// static state (deliberately, like RunTracker), so tests that shared ids would interfere.
/// </remarks>
public class ModPackRegistryTests
{
    private static RsmmIdentity Identity(ulong steamId, string? pack) =>
        new(steamId, OwnsGame: true, Pack: pack, PackName: pack is null ? null : "Pack " + pack);

    [Fact]
    public void Binds_a_verified_ticket_onto_the_user_id_that_login_produced()
    {
        const ulong steamId = 76561197960290001UL;
        const string userId = "user-bind";
        ModPackRegistry.Verified(Identity(steamId, "pack-a"));

        var bound = ModPackRegistry.Bind(userId, steamId);

        Assert.NotNull(bound);
        Assert.Equal("pack-a", bound.Pack);
        Assert.Equal("pack-a", ModPackRegistry.ForUser(userId)?.Pack);
        ModPackRegistry.Remove(userId);
    }

    [Fact]
    public void Reports_no_pack_for_a_login_that_carried_no_ticket()
    {
        // The anonymous tier: `deviceidentifier` logins reach OnLoggedIn with nothing staged, and
        // must come out as "unknown" rather than as some other player's pack.
        Assert.Null(ModPackRegistry.Bind("user-unverified", 76561197960290002UL));
        Assert.Null(ModPackRegistry.ForUser("user-unverified"));
    }

    [Fact]
    public void Consumes_the_staged_entry_so_a_later_login_cannot_inherit_it()
    {
        const ulong steamId = 76561197960290003UL;
        ModPackRegistry.Verified(Identity(steamId, "pack-b"));

        Assert.NotNull(ModPackRegistry.Bind("user-first", steamId));
        Assert.Null(ModPackRegistry.Bind("user-second", steamId));

        ModPackRegistry.Remove("user-first");
    }

    [Fact]
    public void Forgets_a_ticket_whose_login_never_completed()
    {
        const ulong steamId = 76561197960290004UL;
        ModPackRegistry.Verified(Identity(steamId, "pack-c"));

        ModPackRegistry.Forget(steamId);

        Assert.Null(ModPackRegistry.Bind("user-abandoned", steamId));
    }

    [Fact]
    public void Clears_the_pack_when_the_player_logs_out()
    {
        const ulong steamId = 76561197960290005UL;
        const string userId = "user-logout";
        ModPackRegistry.Verified(Identity(steamId, "pack-d"));
        ModPackRegistry.Bind(userId, steamId);

        ModPackRegistry.Remove(userId);

        Assert.Null(ModPackRegistry.ForUser(userId));
    }

    [Fact]
    public void Labels_an_unmodded_player_vanilla()
    {
        Assert.Equal("vanilla", new PlayerPack(1, true, null, null).Label);
    }

    [Fact]
    public void Labels_a_pack_by_name_and_fingerprint_for_the_log()
    {
        Assert.Equal("My pack (abc123)", new PlayerPack(1, true, "abc123", "My pack").Label);
        Assert.Equal("abc123", new PlayerPack(1, true, "abc123", null).Label);
    }
}
