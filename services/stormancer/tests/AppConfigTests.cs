using System.Text.Json;
using Xunit;

namespace Rsmm.Backend.Tests;

/// <summary>
/// Checks that the shipped `deploy/app-config.json` actually binds to <see cref="RsmmOptions"/>.
/// </summary>
/// <remarks>
/// <para>
/// The grid reads the config and hands it to `IConfiguration.GetValue("rsmm", new RsmmOptions())`,
/// which falls back to the defaults for anything it cannot map. A key misspelled in the JSON
/// therefore does not fail — it silently takes the default, and the only visible symptom is logins
/// refusing or the mod-pack rule not firing. There is no command to read the deployed config back,
/// so this is the check that catches it.
/// </para>
/// <para>
/// It deliberately does not assert the values, only that every key is one the class can receive:
/// the values are an operator's choice, the spelling is not.
/// </para>
/// </remarks>
public class AppConfigTests
{
    private static JsonElement RsmmSection()
    {
        // The test binary runs from tests/bin/<cfg>/<tfm>, so walk up to the service root.
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "deploy", "app-config.json")))
        {
            dir = dir.Parent;
        }
        Assert.NotNull(dir);

        var json = File.ReadAllText(Path.Combine(dir.FullName, "deploy", "app-config.json"));
        using var doc = JsonDocument.Parse(json);
        Assert.True(doc.RootElement.TryGetProperty("rsmm", out var section), "app-config.json has no rsmm section");
        return section.Clone();
    }

    [Fact]
    public void Every_key_in_the_rsmm_section_maps_to_an_option()
    {
        var properties = typeof(RsmmOptions).GetProperties().Select(p => p.Name).ToList();

        foreach (var key in RsmmSection().EnumerateObject().Select(p => p.Name))
        {
            // Case-insensitive: the JSON is camelCase, the properties are PascalCase.
            Assert.True(
                properties.Any(name => string.Equals(name, key, StringComparison.OrdinalIgnoreCase)),
                $"app-config.json sets rsmm.{key}, which is not an RsmmOptions property — it would "
                    + $"silently take the default. Known: {string.Join(", ", properties)}");
        }
    }

    [Fact]
    public void The_configured_ticket_key_path_is_an_account_store_id_triple()
    {
        // The grid resolves a secret path as <account>/<store>/<id>; anything else cannot be found,
        // and a missing key means every RSMM ticket is refused.
        var keys = RsmmSection().GetProperty("ticketKeys").EnumerateArray().Select(k => k.GetString()).ToList();

        Assert.NotEmpty(keys);
        foreach (var key in keys)
        {
            Assert.False(string.IsNullOrWhiteSpace(key));
            Assert.Equal(3, key!.Split('/').Length);
        }
    }

    [Fact]
    public void Identity_is_not_required_by_default()
    {
        // Shipping `requireVerifiedIdentity: true` before anything can mint a ticket would lock
        // every player out, so the committed config must leave it off.
        Assert.False(RsmmSection().GetProperty("requireVerifiedIdentity").GetBoolean());
    }

    [Fact]
    public void The_unvalidated_ticket_bypass_is_off_in_the_committed_config()
    {
        // The bypass trusts a SteamID64 nobody checked. Shipping it enabled would let anyone log in
        // as any account, so it must be off here; a local session turns it on with the
        // RSMM_TRUST_UNVERIFIED_STEAM_TICKETS environment variable instead.
        var section = RsmmSection();
        if (section.TryGetProperty("trustUnverifiedSteamTickets", out var flag))
        {
            Assert.False(flag.GetBoolean());
        }
    }

    [Fact]
    public void A_minted_ticket_cannot_outlive_the_configured_maximum_age()
    {
        // The API's DEFAULT_TICKET_TTL_SECONDS is 300. If the grid's cap were lower, every ticket
        // the API mints at its default would be refused as too old.
        Assert.True(RsmmSection().GetProperty("maxTicketAgeSeconds").GetInt32() >= 300);
    }
}
