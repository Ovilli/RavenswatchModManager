import type { Session } from './auth.js';

export type AppEnv = {
  Variables: {
    user: Session['user'] | null;
    session: Session['session'] | null;
  };
};
