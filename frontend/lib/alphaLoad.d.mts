export function loadAlphaWithRetry<T>(load: () => Promise<T>, options?: {
  active?: () => boolean;
  onRetry?: () => void;
  wait?: (milliseconds: number) => Promise<unknown>;
}): Promise<T | undefined>;
