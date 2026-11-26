import { describe, expect, it } from "vitest";

import { profileBounds, profilePoints } from "../workbench/profile/ProfilePanel";

describe("the profile", () => {
  it("takes the server's mean profile, lowest height first, without the null points", () => {
    const result = {
      mean_profile: [
        { height_m: 100, mean_speed: 8.4 },
        { height_m: 60, mean_speed: 7.8 },
        { height_m: 80, mean_speed: null },
      ],
    } as unknown as Parameters<typeof profilePoints>[0];
    expect(profilePoints(result)).toEqual([
      { height: 60, speed: 7.8 },
      { height: 100, speed: 8.4 },
    ]);
    expect(profilePoints(undefined)).toEqual([]);
  });

  it("bounds both profiles from zero to a round top", () => {
    expect(profileBounds([{ height: 100, speed: 8.4 }], [{ height: 60, speed: 9.9 }])).toEqual({ speed: 12, height: 120 });
    expect(profileBounds([])).toEqual({ speed: 2, height: 20 });
  });
});
