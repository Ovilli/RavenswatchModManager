using Xunit;

namespace Rsmm.Backend.Tests;

/// <summary>
/// Reading a SteamID64 out of an unvalidated Steam ticket (the local-testing path).
/// </summary>
public class SteamTicketTests
{
    /// <summary>A real individual SteamID64 — universe 1, type 1, account 1391497335.</summary>
    private const ulong RealSteamId = 76561199351763063UL;

    /// <summary>
    /// A Steam app ticket's leading section, as the layout the conventional offset assumes:
    /// a 20-byte GC-token section (its length, then an 8-byte token), then the SteamID64 at 12.
    /// </summary>
    private static byte[] AppTicket(ulong steamId, ulong gcToken = 0x0102030405060708UL)
    {
        var bytes = new List<byte>();
        bytes.AddRange(BitConverter.GetBytes(20u));
        bytes.AddRange(BitConverter.GetBytes(gcToken));
        bytes.AddRange(BitConverter.GetBytes(steamId));
        bytes.AddRange(BitConverter.GetBytes(0xDEADBEEFu));
        return bytes.ToArray();
    }

    private static string Hex(byte[] bytes) => Convert.ToHexString(bytes);

    [Fact]
    public void Reads_the_steam_id_from_a_hex_ticket()
    {
        Assert.True(SteamTicket.TryReadSteamId(Hex(AppTicket(RealSteamId)), out var id, out var error));
        Assert.Equal(RealSteamId, id);
        Assert.Equal("", error);
    }

    [Fact]
    public void Reads_the_steam_id_from_a_base64_ticket()
    {
        var ticket = Convert.ToBase64String(AppTicket(RealSteamId));

        Assert.True(SteamTicket.TryReadSteamId(ticket, out var id, out _));
        Assert.Equal(RealSteamId, id);
    }

    [Fact]
    public void Accepts_lowercase_hex()
    {
        Assert.True(SteamTicket.TryReadSteamId(Hex(AppTicket(RealSteamId)).ToLowerInvariant(), out var id, out _));
        Assert.Equal(RealSteamId, id);
    }

    [Fact]
    public void Finds_the_id_even_when_the_leading_sections_are_a_different_size()
    {
        // The whole reason the id is found by structure: a layout change moves it off offset 12,
        // where a fixed read would return eight bytes of something else.
        var shifted = new byte[7].Concat(AppTicket(RealSteamId)).ToArray();

        Assert.True(SteamTicket.TryReadSteamId(Hex(shifted), out var id, out _));
        Assert.Equal(RealSteamId, id);
    }

    [Fact]
    public void Prefers_the_conventional_offset_when_a_ticket_names_several_accounts()
    {
        const ulong other = 76561199351763064UL;
        var ticket = AppTicket(RealSteamId).Concat(BitConverter.GetBytes(other)).ToArray();

        Assert.True(SteamTicket.TryReadSteamId(Hex(ticket), out var id, out _));
        Assert.Equal(RealSteamId, id);
    }

    [Fact]
    public void Refuses_an_ambiguous_ticket_with_no_id_at_the_conventional_offset()
    {
        // Two candidates and neither where one is expected: picking either would be a silent
        // wrong answer, so it fails instead.
        var ticket = new byte[7]
            .Concat(BitConverter.GetBytes(76561199351763063UL))
            .Concat(BitConverter.GetBytes(76561199351763064UL))
            .ToArray();

        Assert.False(SteamTicket.TryReadSteamId(Hex(ticket), out _, out var error));
        Assert.Contains("ambiguous", error);
    }

    [Fact]
    public void Refuses_a_ticket_with_nothing_steam_shaped_in_it()
    {
        Assert.False(SteamTicket.TryReadSteamId(Hex(new byte[64]), out _, out var error));
        Assert.Contains("no SteamID64", error);
    }

    [Theory]
    [InlineData(0UL)]                    // empty
    [InlineData(76561197960265727UL)]    // one below the lowest individual id
    [InlineData(103582791429521408UL)]   // a group id (type 7), not a player
    public void Does_not_accept_a_value_that_is_not_an_individual_account(ulong notAPlayer)
    {
        var ticket = new byte[4].Concat(BitConverter.GetBytes(notAPlayer)).Concat(new byte[4]).ToArray();

        Assert.False(SteamTicket.TryReadSteamId(Hex(ticket), out _, out _));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void Refuses_an_empty_ticket(string? ticket)
    {
        Assert.False(SteamTicket.TryReadSteamId(ticket, out _, out var error));
        Assert.Equal("empty ticket", error);
    }

    [Theory]
    [InlineData("not hex and not base64 !!!")]
    [InlineData("ABC")]
    public void Refuses_a_ticket_that_decodes_as_neither_hex_nor_base64(string ticket)
    {
        Assert.False(SteamTicket.TryReadSteamId(ticket, out _, out var error));
        Assert.Contains("neither hex nor base64", error);
    }

    [Fact]
    public void Refuses_a_ticket_too_short_to_hold_an_id()
    {
        Assert.False(SteamTicket.TryReadSteamId("AABB", out _, out var error));
        Assert.Contains("bytes", error);
    }
}
