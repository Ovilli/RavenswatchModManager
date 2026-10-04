using System.Collections.Concurrent;
using Stormancer.Diagnostics;
using Stormancer.Server.Plugins.GameSession;

namespace Rsmm.Backend;

/// <summary>
/// Which users are inside a started game session (a run).
/// </summary>
/// <remarks>
/// Process-wide: correct on a single-node grid, where party and gamesession scenes share a
/// process. A multi-node grid would need this in the cluster's distributed cache instead.
/// </remarks>
public static class RunTracker
{
    private static readonly ConcurrentDictionary<string, string> UserToSession = new();

    public static bool IsInRun(string userId) => UserToSession.ContainsKey(userId);

    internal static void Started(string sessionId, IEnumerable<string> userIds)
    {
        foreach (var userId in userIds)
        {
            UserToSession[userId] = sessionId;
        }
    }

    internal static void Completed(string sessionId)
    {
        foreach (var (userId, session) in UserToSession)
        {
            if (session == sessionId)
            {
                UserToSession.TryRemove(userId, out _);
            }
        }
    }
}

public class RunTrackerGameSessionHandler : IGameSessionEventHandler
{
    private readonly ILogger _logger;

    public RunTrackerGameSessionHandler(ILogger logger)
    {
        _logger = logger;
    }

    public Task GameSessionStarted(GameSessionStartedCtx ctx)
    {
        var userIds = ctx.Peers.Select(p => p.Player.UserId).ToList();
        RunTracker.Started(ctx.Scene.Id, userIds);
        _logger.Log(LogLevel.Info, "rsmm.runs", "Run started", new { gameSession = ctx.Scene.Id, userIds });
        return Task.CompletedTask;
    }

    public Task GameSessionCompleted(GameSessionCompleteCtx ctx)
    {
        RunTracker.Completed(ctx.Scene.Id);
        _logger.Log(LogLevel.Info, "rsmm.runs", "Run completed", new { gameSession = ctx.Scene.Id });
        return Task.CompletedTask;
    }
}
