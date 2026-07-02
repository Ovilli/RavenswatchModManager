import type { Session } from './auth.js';
import type { Logger } from './logger.js';

export type AppEnv = {
  Variables: {
    user: Session['user'] | null;
    session: Session['session'] | null;
    // Set by the session middleware when a signed-in user is banned. `user` is
    // nulled (treated as anonymous everywhere), but this preserves the ban so a
    // dedicated status endpoint can tell the frontend to show a ban notice.
    bannedInfo: { banned: true; reason: string | null } | null;
    requestId: string;
    log: Logger;
  };
};
