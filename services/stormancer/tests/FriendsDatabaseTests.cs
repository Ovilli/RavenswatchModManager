using Microsoft.EntityFrameworkCore;
using RsmmBackend;
using Stormancer.Server.Hosting;
using Stormancer.Server.Plugins.Database.EntityFrameworkCore;
using Xunit;

namespace Rsmm.Backend.Tests;

/// <summary>
/// The Friends plugin must have a database to talk to. Without one, every party join failed:
/// the Party plugin checks block lists through Friends, and each Friends query threw
/// "No database provider has been configured for this DbContext" (grid log, 2026-10-05).
/// </summary>
public class FriendsDatabaseTests
{
    [Fact]
    public async Task The_app_host_gives_friends_a_queryable_database()
    {
        // The same startup actions as Program.cs, without connecting to a grid.
        var host = ServerApplication.CreateDesignTimeHost(builder => builder
            .AddAllStartupActions()
            .AddStartupAction(appBuilder => new App().Register(appBuilder)));
        await using var scope = host.DependencyResolver.CreateChild(Stormancer.Server.Plugins.API.Constants.ApiRequestTag);

        var db = await scope.Resolve<DbContextAccessor>().GetDbContextAsync();
        Assert.Equal("Microsoft.EntityFrameworkCore.InMemory", db.Database.ProviderName);

        // Every entity the Friends plugin maps must answer a query (empty is fine): this is
        // exactly what the block-list check does when a player joins a party.
        var friendsTypes = db.Model.GetEntityTypes()
            .Where(t => t.ClrType.Namespace?.Contains("Friends", StringComparison.Ordinal) == true)
            .ToList();
        Assert.NotEmpty(friendsTypes);
        var set = typeof(DbContext).GetMethod(nameof(DbContext.Set), Type.EmptyTypes)!;
        foreach (var type in friendsTypes)
        {
            var query = (IQueryable)set.MakeGenericMethod(type.ClrType).Invoke(db, null)!;
            Assert.Equal(0, query.Cast<object>().Count());
        }
    }
}
