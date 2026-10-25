import { useEffect, useReducer, useState } from 'react';
import { connectLive, DEFAULT_DATABASE, DEFAULT_HOST, type LiveHandlers, type LiveSnapshot } from '../live';

export const LIVE_HOST = import.meta.env.VITE_SPACETIMEDB_HOST || DEFAULT_HOST;
export const LIVE_DATABASE = import.meta.env.VITE_SPACETIMEDB_DB || DEFAULT_DATABASE;

type ConnectionState = {
  status: Parameters<LiveHandlers['status']>[0];
  detail?: string;
  snapshot?: LiveSnapshot;
  updatedAt?: Date;
};

/** One subscription per mounted dashboard; retain recorded data while reconnecting. */
export function useLiveStore() {
  const [state, setState] = useState<ConnectionState>({ status: 'connecting' });
  const [attempt, reconnect] = useReducer((value: number) => value + 1, 0);

  useEffect(() => {
    let disposed = false;
    let generation = 0;
    let stop: (() => void) | undefined;
    const close = () => {
      generation++;
      stop?.();
      stop = undefined;
    };
    const start = () => {
      close();
      const current = generation;
      const active = () => !disposed && current === generation;
      setState(previous => ({ ...previous, status: 'connecting', detail: undefined }));
      stop = connectLive({
        status: (status, detail) => {
          if (active()) setState(previous => ({ ...previous, status, detail }));
        },
        snapshot: snapshot => {
          if (active()) setState(previous => ({ ...previous, snapshot, updatedAt: new Date() }));
        },
      }, LIVE_HOST, LIVE_DATABASE);
    };
    const hide = () => {
      close();
      setState(previous => ({ ...previous, status: 'disconnected', detail: undefined }));
    };
    const show = (event: PageTransitionEvent) => { if (event.persisted) start(); };

    start();
    window.addEventListener('pagehide', hide);
    window.addEventListener('pageshow', show);
    return () => {
      disposed = true;
      close();
      window.removeEventListener('pagehide', hide);
      window.removeEventListener('pageshow', show);
    };
  }, [attempt]);

  return { ...state, reconnect };
}
