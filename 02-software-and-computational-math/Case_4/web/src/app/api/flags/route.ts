import { NextResponse } from "next/server";
import { computeNeighbourhoodFlags } from "@/lib/data/flags";

export async function GET() {
  const result = await computeNeighbourhoodFlags();
  return NextResponse.json(result);
}
