using System.Text;
using System.Text.Json;
using Xunit;

namespace Rsmm.Backend.Tests;

public class RsmmTicketVerifierTests
{
    private static readonly byte[] Key = TicketMint.Key("a-test-ticket-key");
    private static readonly byte[] OtherKey = TicketMint.Key("a-different-key");

    private static RsmmTicketVerifier Verifier(RsmmOptions? options = null, params byte[][] keys) =>
        new(keys.Length == 0 ? [Key] : keys, options ?? new RsmmOptions());

    [Fact]
    public void Accepts_a_freshly_minted_ticket_and_reads_every_field()
    {
        var identity = Verifier().Verify(TicketMint.Mint(Key), out var error);

        Assert.NotNull(identity);
        Assert.Equal("", error);
        Assert.Equal(76561197960287930UL, identity.SteamId);
        Assert.True(identity.OwnsGame);
        Assert.Equal("a1b2c3d4e5f60718", identity.Pack);
        Assert.Equal("Test pack", identity.PackName);
    }

    [Fact]
    public void Treats_an_unmodded_player_as_a_null_pack()
    {
        var identity = Verifier().Verify(TicketMint.Mint(Key, pack: null, packName: null), out _);

        Assert.NotNull(identity);
        Assert.Null(identity.Pack);
        Assert.Null(identity.PackName);
    }

    [Fact]
    public void Treats_a_blank_pack_as_no_pack()
    {
        // The minter may send "" rather than omitting the field; "" and null must not be two
        // different packs, or an unmodded player would fail to match another unmodded player.
        var identity = Verifier().Verify(TicketMint.Mint(Key, pack: "   ", packName: ""), out _);

        Assert.NotNull(identity);
        Assert.Null(identity.Pack);
        Assert.Null(identity.PackName);
    }

    [Fact]
    public void Rejects_a_ticket_signed_with_an_unknown_key()
    {
        Assert.Null(Verifier().Verify(TicketMint.Mint(OtherKey), out var error));
        Assert.Equal("bad signature", error);
    }

    [Fact]
    public void Rejects_a_payload_edited_after_signing()
    {
        // The whole point of the scheme: a client that rewrites its own SteamID is refused.
        var ticket = TicketMint.Mint(Key, steamId: 76561197960287930UL);
        var parts = ticket.Split('.');
        var forged = JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            ["sid"] = "76561197960287931",
            ["own"] = true,
            ["iat"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
            ["exp"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds() + 300,
            ["jti"] = "forged",
        });
        var tampered = $"{parts[0]}.{TicketMint.Base64Url(Encoding.UTF8.GetBytes(forged))}.{parts[2]}";

        Assert.Null(Verifier().Verify(tampered, out var error));
        Assert.Equal("bad signature", error);
    }

    [Fact]
    public void Accepts_a_ticket_signed_with_any_configured_key_so_a_key_can_be_rotated()
    {
        var verifier = Verifier(keys: [OtherKey, Key]);

        Assert.NotNull(verifier.Verify(TicketMint.Mint(Key), out _));
        Assert.NotNull(verifier.Verify(TicketMint.Mint(OtherKey), out _));
    }

    [Fact]
    public void Refuses_everything_when_no_key_is_configured()
    {
        // A missing secret must fail closed: an empty key list cannot be allowed to mean
        // "skip the signature check".
        var verifier = new RsmmTicketVerifier([], new RsmmOptions());

        Assert.False(verifier.Enabled);
        Assert.Null(verifier.Verify(TicketMint.Mint(Key), out var error));
        Assert.Equal("no ticket key configured", error);
    }

    [Fact]
    public void Ignores_an_empty_key_rather_than_trusting_it()
    {
        var verifier = new RsmmTicketVerifier([[]], new RsmmOptions());

        Assert.False(verifier.Enabled);
    }

    [Fact]
    public void Rejects_an_expired_ticket()
    {
        var old = DateTimeOffset.UtcNow.ToUnixTimeSeconds() - 1000;
        var ticket = TicketMint.Mint(Key, issuedAt: old, expires: old + 60);

        Assert.Null(Verifier().Verify(ticket, out var error));
        Assert.Equal("ticket expired", error);
    }

    [Fact]
    public void Rejects_a_ticket_issued_in_the_future_beyond_the_skew()
    {
        var ahead = DateTimeOffset.UtcNow.ToUnixTimeSeconds() + 3600;

        Assert.Null(Verifier().Verify(TicketMint.Mint(Key, issuedAt: ahead), out var error));
        Assert.Equal("ticket issued in the future", error);
    }

    [Fact]
    public void Tolerates_a_mint_clock_inside_the_configured_skew()
    {
        var options = new RsmmOptions { ClockSkewSeconds = 120 };
        var ahead = DateTimeOffset.UtcNow.ToUnixTimeSeconds() + 60;

        Assert.NotNull(Verifier(options).Verify(TicketMint.Mint(Key, issuedAt: ahead), out _));
    }

    [Fact]
    public void Rejects_a_ticket_older_than_the_configured_maximum_age()
    {
        // Still inside its own exp, but minted long enough ago that we no longer accept it:
        // the age cap is what bounds the replay window across a grid restart.
        var options = new RsmmOptions { MaxTicketAgeSeconds = 60, ClockSkewSeconds = 0 };
        var issued = DateTimeOffset.UtcNow.ToUnixTimeSeconds() - 600;
        var ticket = TicketMint.Mint(Key, issuedAt: issued, expires: issued + 7200);

        Assert.Null(Verifier(options).Verify(ticket, out var error));
        Assert.Equal("ticket older than the configured maximum age", error);
    }

    [Fact]
    public void Rejects_a_ticket_with_no_validity_window()
    {
        var ticket = TicketMint.Sign(Key, """{"sid":"76561197960287930","jti":"x"}""");

        Assert.Null(Verifier().Verify(ticket, out var error));
        Assert.Equal("ticket has no validity window", error);
    }

    [Fact]
    public void Accepts_a_ticket_once_and_refuses_the_replay()
    {
        var verifier = Verifier();
        var ticket = TicketMint.Mint(Key);

        Assert.NotNull(verifier.Verify(ticket, out _));
        Assert.Null(verifier.Verify(ticket, out var error));
        Assert.Equal("ticket already used", error);
    }

    [Fact]
    public void Rejects_a_ticket_with_no_id_because_it_could_not_be_replay_checked()
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var ticket = TicketMint.Mint(Key, jti: "");

        Assert.Null(Verifier().Verify(ticket, out var error));
        Assert.Equal("ticket has no id", error);
        Assert.True(now > 0);
    }

    [Theory]
    [InlineData("76561197960265727")] // one below the lowest real SteamID64
    [InlineData("0")]
    [InlineData("not-a-number")]
    [InlineData("")]
    public void Rejects_a_payload_whose_steam_id_is_not_a_SteamID64(string sid)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var ticket = TicketMint.Sign(Key, JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            ["sid"] = sid,
            ["iat"] = now,
            ["exp"] = now + 300,
            ["jti"] = Guid.NewGuid().ToString("N"),
        }));

        Assert.Null(Verifier().Verify(ticket, out var error));
        Assert.Equal("payload carries no usable SteamID64", error);
    }

    [Theory]
    [InlineData("")]
    [InlineData("rsmm1")]
    [InlineData("rsmm1.onlytwo")]
    [InlineData("rsmm1.a.b.c")]
    [InlineData("rsmm2.a.b")]
    [InlineData("jwt.a.b")]
    public void Rejects_anything_that_is_not_a_v1_ticket(string ticket)
    {
        Assert.Null(Verifier().Verify(ticket, out var error));
        Assert.Equal("malformed ticket", error);
    }

    [Fact]
    public void Rejects_a_signature_that_is_not_base64url()
    {
        var parts = TicketMint.Mint(Key).Split('.');

        Assert.Null(Verifier().Verify($"{parts[0]}.{parts[1]}.not base64!", out var error));
        Assert.Equal("malformed signature", error);
    }

    [Fact]
    public void Rejects_a_base64_length_that_cannot_be_padded()
    {
        // length % 4 == 1 is an impossible base64 string. Padding it to something Convert accepts
        // would decode attacker-chosen bytes; it has to be refused outright.
        var parts = TicketMint.Mint(Key).Split('.');
        var impossible = parts[2][..(parts[2].Length / 4 * 4 + 1)];

        Assert.Null(Verifier().Verify($"{parts[0]}.{parts[1]}.{impossible}", out var error));
        Assert.Equal("malformed signature", error);
    }

    [Fact]
    public void Rejects_a_payload_that_is_signed_but_is_not_json()
    {
        var payload = TicketMint.Base64Url(Encoding.UTF8.GetBytes("not json at all"));
        var signed = $"{RsmmTicketVerifier.Prefix}.{payload}";
        var signature = TicketMint.Base64Url(
            System.Security.Cryptography.HMACSHA256.HashData(Key, Encoding.ASCII.GetBytes(signed)));

        Assert.Null(Verifier().Verify($"{signed}.{signature}", out var error));
        Assert.StartsWith("unreadable payload", error);
    }

    [Theory]
    [InlineData("rsmm1.abc.def", true)]
    [InlineData("rsmm1.", true)]
    [InlineData("rsmm1", false)]
    [InlineData("rsmm2.abc.def", false)]
    [InlineData("", false)]
    [InlineData(null, false)]
    public void Recognises_our_own_tickets_so_real_steam_tickets_still_reach_steam(string? candidate, bool expected)
    {
        Assert.Equal(expected, RsmmTicketVerifier.LooksLikeTicket(candidate));
    }
}
