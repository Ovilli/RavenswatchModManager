import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { watchAppLaunch } from './app-launch';

let windowEvents: EventTarget;
let page: EventTarget & { visibilityState: string; hasFocus: () => boolean };
let focused: boolean;
let stop: (() => void) | undefined;

beforeEach(() => {
  vi.useFakeTimers();
  focused = true;
  windowEvents = new EventTarget();
  page = Object.assign(new EventTarget(), {
    visibilityState: 'visible',
    hasFocus: () => focused,
  });
  vi.stubGlobal('window', Object.assign(windowEvents, { setTimeout, clearTimeout }));
  vi.stubGlobal('document', page);
});

afterEach(() => {
  stop?.();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('app launch fallback', () => {
  it('offers downloads when a launch leaves the page visible and focused', () => {
    const fallback = vi.fn();
    const settled = vi.fn();
    stop = watchAppLaunch(fallback, settled);
    vi.advanceTimersByTime(1999);
    expect(fallback).not.toHaveBeenCalled();
    expect(settled).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fallback).toHaveBeenCalledOnce();
    expect(settled).toHaveBeenCalledOnce();
    windowEvents.dispatchEvent(new Event('focus'));
    vi.runAllTimers();
    expect(fallback).toHaveBeenCalledOnce();
  });

  it('does not show downloads on return from a likely app handoff', () => {
    const fallback = vi.fn();
    const settled = vi.fn();
    stop = watchAppLaunch(fallback, settled);
    page.visibilityState = 'hidden';
    page.dispatchEvent(new Event('visibilitychange'));
    page.visibilityState = 'visible';
    page.dispatchEvent(new Event('visibilitychange'));
    windowEvents.dispatchEvent(new Event('focus'));
    vi.runAllTimers();
    expect(fallback).not.toHaveBeenCalled();
    expect(settled).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('waits for a browser prompt to close, then gives the app time to open', () => {
    const fallback = vi.fn();
    stop = watchAppLaunch(fallback);
    focused = false;
    windowEvents.dispatchEvent(new Event('blur'));
    vi.advanceTimersByTime(30_000);
    expect(fallback).not.toHaveBeenCalled();
    focused = true;
    windowEvents.dispatchEvent(new Event('focus'));
    vi.advanceTimersByTime(1999);
    expect(fallback).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fallback).toHaveBeenCalledOnce();
  });

  it('cancels a pending fallback when accepting the prompt hides the page', () => {
    const fallback = vi.fn();
    stop = watchAppLaunch(fallback);
    windowEvents.dispatchEvent(new Event('blur'));
    windowEvents.dispatchEvent(new Event('focus'));
    vi.advanceTimersByTime(500);
    page.visibilityState = 'hidden';
    page.dispatchEvent(new Event('visibilitychange'));
    vi.runAllTimers();
    expect(fallback).not.toHaveBeenCalled();
  });

  it('does not interrupt an unfocused page even if the blur event was missed', () => {
    const fallback = vi.fn();
    stop = watchAppLaunch(fallback);
    focused = false;
    vi.advanceTimersByTime(3000);
    expect(fallback).not.toHaveBeenCalled();
    focused = true;
    windowEvents.dispatchEvent(new Event('focus'));
    vi.runAllTimers();
    expect(fallback).toHaveBeenCalledOnce();
  });

  it('cancels on navigation and leaves no listeners that can restart the timer', () => {
    const fallback = vi.fn();
    const settled = vi.fn();
    stop = watchAppLaunch(fallback, settled);
    windowEvents.dispatchEvent(new Event('pagehide'));
    windowEvents.dispatchEvent(new Event('focus'));
    vi.runAllTimers();
    expect(fallback).not.toHaveBeenCalled();
    expect(settled).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('lets a new attempt replace the previous one without duplicate dialogs', () => {
    const firstFallback = vi.fn();
    const secondFallback = vi.fn();
    stop = watchAppLaunch(firstFallback);
    vi.advanceTimersByTime(1000);
    stop();
    stop = watchAppLaunch(secondFallback);
    vi.advanceTimersByTime(1000);
    expect(firstFallback).not.toHaveBeenCalled();
    expect(secondFallback).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(secondFallback).toHaveBeenCalledOnce();
  });

  it('cleans up when the component unmounts or downloads are opened directly', () => {
    const fallback = vi.fn();
    const settled = vi.fn();
    stop = watchAppLaunch(fallback, settled);
    stop();
    windowEvents.dispatchEvent(new Event('focus'));
    vi.runAllTimers();
    expect(fallback).not.toHaveBeenCalled();
    expect(settled).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});
