using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;
using Stormancer.Server.Plugins.Database.EntityFrameworkCore;

namespace Rsmm.Backend;

/// <summary>
/// Gives the Entity Framework plugin an in-memory database, so the Friends plugin has
/// somewhere to read and write without a database server.
/// </summary>
/// <remarks>
/// Without ANY provider, every Friends query threw "No database provider has been configured
/// for this DbContext" — and the Party plugin asks Friends for block lists when a player joins
/// a party (FriendsPartyCompatibilityPolicy → GetBlockedLists), so every join failed with
/// "Insufficient data" and no run could start (grid log, 2026-10-05: 5 parties created, 6 joins,
/// 0 succeeded).
///
/// In memory, the block-list check reads empty tables, finds nobody blocked and lets the join
/// through. Friend and block lists made in game work until the grid restarts, then are gone.
/// A real database (Stormancer.Server.Plugins.Database.EntityFrameworkCore.Npgsql plus
/// migrations) would make them persist.
/// </remarks>
public class InMemoryDatabase : IDbContextLifecycleHandler
{
    public bool IsConfigured => true;

    public Task OnPreInit(InitializeDbContext ctx) => Task.CompletedTask;

    public void OnConfiguring(DbContextOptionsBuilder optionsBuilder, string contextId, Dictionary<string, object> customData)
    {
        // One store per context id: contexts with different models must not share tables.
        optionsBuilder.UseInMemoryDatabase($"rsmm-{contextId}");
    }
}

/// <summary>
/// Stores <see cref="JsonDocument"/> properties as JSON text for <see cref="InMemoryDatabase"/>.
/// </summary>
/// <remarks>
/// The plugins' entities (Friends' MemberRecord.CustomData among them) carry JsonDocument
/// properties that PostgreSQL maps to a jsonb column. The in-memory provider has no such type,
/// so model building tried to make JsonDocument an entity of its own and failed ("No suitable
/// constructor was found for entity type 'JsonDocument'"), which broke the Friends queries just
/// as surely as having no provider at all.
/// </remarks>
public class InMemoryJsonDocuments : IDbModelBuilder
{
    private static readonly ValueConverter<JsonDocument, string> AsText = new(
        doc => doc.RootElement.GetRawText(),
        text => JsonDocument.Parse(text, default));

    public void OnModelCreating(ModelBuilder modelBuilder, string contextId, Dictionary<string, object> customData)
    {
        modelBuilder.Ignore<JsonDocument>();
        foreach (var entity in modelBuilder.Model.GetEntityTypes().ToList())
        {
            foreach (var prop in entity.ClrType.GetProperties().Where(p => p.PropertyType == typeof(JsonDocument)))
            {
                modelBuilder.Entity(entity.ClrType).Property(prop.Name).HasConversion(AsText);
            }
        }
    }
}
