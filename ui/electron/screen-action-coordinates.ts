import type { ControlScreenCoordinates } from "../shared-types.js";

export type ScreenBounds = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type ScreenPoint = {
  x: number;
  y: number;
};

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

export const resolveScreenActionPoint = (
  coordinates: ControlScreenCoordinates,
  bounds: ScreenBounds,
): ScreenPoint => {
  if (isFiniteNumber(coordinates.x) && isFiniteNumber(coordinates.y)) {
    return {
      x: Math.round(bounds.x + coordinates.x),
      y: Math.round(bounds.y + coordinates.y),
    };
  }

  return {
    x: Math.round(bounds.x + coordinates.x_ratio * bounds.width),
    y: Math.round(bounds.y + coordinates.y_ratio * bounds.height),
  };
};
