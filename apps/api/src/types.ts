import type { Session } from './auth.js';
import type { Logger } from './logger.js';

export type AppEnv = {
  Variables: {
    user: Session['user'] | null;
    session: Session['session'] | null;
    requestId: string;
    log: Logger;
  };
};
