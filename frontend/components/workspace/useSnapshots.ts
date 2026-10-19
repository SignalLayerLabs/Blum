"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { loadAlphaWithRetry } from "@/lib/alphaLoad.mjs";
export function useSnapshots(readers: Record<string, () => Promise<any>>) {
  const [data, setData] = useState<Record<string, any>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(true);
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setPending(true);
    setErrors({});
    async function load() {
      // Sequential reads avoid making the CPU runtime calculate several cold views at once.
      for (const [key, reader] of Object.entries(readers)) {
        if (!active) return;
        try {
          const value = await loadAlphaWithRetry(reader, {
            active: () => active,
          });
          if (active && value !== undefined)
            setData((old) => ({ ...old, [key]: value }));
        } catch (error) {
          if (active)
            setErrors((old) => ({
              ...old,
              [key]: error instanceof Error ? error.message : String(error),
            }));
        }
      }
      if (active) {
        setPending(false);
        setCheckedAt(Date.now());
        timer = setTimeout(() => {
          if (document.visibilityState === "visible")
            setRefreshKey((key) => key + 1);
          else timer = setTimeout(checkVisible, 10000);
        }, 60000);
      }
    }
    function checkVisible() {
      if (!active) return;
      if (document.visibilityState === "visible")
        setRefreshKey((key) => key + 1);
      else timer = setTimeout(checkVisible, 10000);
    }
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [readers, refreshKey]);
  return {
    data,
    errors,
    pending,
    checkedAt,
    refresh: () => setRefreshKey((key) => key + 1),
  };
}
export const overviewReaders = {
  runtime: api.operatingState,
  brain: api.traderBrain,
  paper: () => api.traderPaperTrading(20),
  desk: api.alphaDesk,
};
export const callReaders = { desk: api.alphaDesk };
export const tradeReaders = { paper: () => api.traderPaperTrading(50) };
export const performanceReaders = {
  desk: api.alphaDesk,
  paper: () => api.traderPaperTrading(20),
};
export const researchReaders = {
  curriculum: api.tradingCurriculum,
  training: api.traderTrainingGround,
};
