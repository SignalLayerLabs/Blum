const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// One retry tolerates a cold read without concealing persistent failures.
export async function loadAlphaWithRetry(load, {active = () => true, onRetry = () => {}, wait = pause} = {}) {
  if (!active()) return undefined;
  try {
    return await load();
  } catch (error) {
    if (!active()) return undefined;
    const transient = ['AbortError', 'TimeoutError', 'TypeError'].includes(error?.name)
      || /^50[234]\b/.test(String(error?.message ?? ''));
    if (!transient) throw error;
    onRetry();
    await wait(1000);
    if (!active()) return undefined;
    return load();
  }
}
