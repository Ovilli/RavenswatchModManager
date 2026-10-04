using Xunit;

namespace Rsmm.Backend.Tests;

/// <summary>
/// Pins the wire format against a vector derived outside this codebase.
/// </summary>
/// <remarks>
/// <para>
/// Every other test mints with <see cref="TicketMint"/> and verifies with
/// <see cref="RsmmTicketVerifier"/>, so the two could agree on a format that is wrong and still
/// pass. This vector was produced independently (Python <c>hmac</c>/<c>base64.urlsafe_b64encode</c>)
/// from the key and payload below, so it fails if either side drifts.
/// </para>
/// <para>
/// The TypeScript minter in <c>apps/api</c> has to reproduce the same ticket from the same inputs.
/// It is the only contract between the two languages, and a mismatch means every login is refused.
/// </para>
/// </remarks>
public class TicketVectorTests
{
    private const string VectorKey = "rsmm-vector-key";

    /// <summary>Exactly the JSON that was signed — key order and spacing included.</summary>
    private const string VectorPayload =
        """{"sid":"76561197960287930","own":true,"pack":"a1b2c3d4e5f60718","packName":"Vector pack","iat":1760000000,"exp":1760000300,"jti":"vector-0001"}""";

    private const string VectorTicket =
        "rsmm1.eyJzaWQiOiI3NjU2MTE5Nzk2MDI4NzkzMCIsIm93biI6dHJ1ZSwicGFjayI6ImExYjJjM2Q0ZTVmNjA3MTgi" +
        "LCJwYWNrTmFtZSI6IlZlY3RvciBwYWNrIiwiaWF0IjoxNzYwMDAwMDAwLCJleHAiOjE3NjAwMDAzMDAsImp0aSI6In" +
        "ZlY3Rvci0wMDAxIn0.h4lMbeKjFx-c5m7tRCpnWtIeNvT5yAA64LD1r5zLY-M";

    [Fact]
    public void Mints_the_vector_ticket_byte_for_byte()
    {
        Assert.Equal(VectorTicket, TicketMint.Sign(TicketMint.Key(VectorKey), VectorPayload));
    }

    [Fact]
    public void Verifies_the_vector_ticket_and_reads_its_fields()
    {
        // The vector's own exp is in the past, so the time checks have to be opened up to accept it.
        // Only those are relaxed; the signature is verified exactly as in production. int.MaxValue
        // on both windows is also the regression test for the overflow this test first caught: the
        // two are added together, and at int width the sum wrapped negative and rejected the ticket.
        var options = new RsmmOptions { MaxTicketAgeSeconds = int.MaxValue, ClockSkewSeconds = int.MaxValue };
        var verifier = new RsmmTicketVerifier([TicketMint.Key(VectorKey)], options);

        var identity = verifier.Verify(VectorTicket, out var error);

        Assert.NotNull(identity);
        Assert.Equal("", error);
        Assert.Equal(76561197960287930UL, identity.SteamId);
        Assert.True(identity.OwnsGame);
        Assert.Equal("a1b2c3d4e5f60718", identity.Pack);
        Assert.Equal("Vector pack", identity.PackName);
    }
}
