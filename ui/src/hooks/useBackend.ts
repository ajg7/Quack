import { useQuery } from "@tanstack/react-query";
import { fetchHealth, fetchModels, fetchSources } from "../lib/api";

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 15_000 });
}

export function useModels() {
  return useQuery({ queryKey: ["models"], queryFn: fetchModels, staleTime: Infinity });
}

export function useSources() {
  return useQuery({ queryKey: ["sources"], queryFn: fetchSources, staleTime: 5 * 60_000 });
}
