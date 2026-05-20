import type { Session } from './auth';

export type AppEnv = {
  Variables: {
    user: Session['user'] | null;
    session: Session['session'] | null;
  };
};
