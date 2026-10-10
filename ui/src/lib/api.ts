import axios from "axios";
import { API_URL } from "../config";
import { healthSchema, sourcesSchema } from "./schemas";
import type { Health, Sources } from "./schemas";

const client = axios.create({ baseURL: API_URL, adapter: "fetch", timeout: 20_000 });

export async function fetchHealth(): Promise<Health> {
  const response = await client.get("/health");
  return healthSchema.parse(response.data);
}

export async function fetchSources(): Promise<Sources> {
  const response = await client.get("/sources");
  return sourcesSchema.parse(response.data);
}

export async function clearSession(sessionId: string): Promise<void> {
  await client.delete(`/sessions/${encodeURIComponent(sessionId)}`);
}
