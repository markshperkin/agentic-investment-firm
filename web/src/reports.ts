import { getReport } from "./api";

// Per-run report cache so the Report tab is instant and can be warmed ahead of time.
const cache = new Map<string, any>();

export function cachedReport(runId: string): any | undefined {
  return cache.get(runId);
}

export async function prefetchReport(runId: string): Promise<any> {
  const r = await getReport(runId);
  cache.set(runId, r);
  return r;
}
