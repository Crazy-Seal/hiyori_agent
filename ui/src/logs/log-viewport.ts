export class LogViewportState {
  private userScrolling = false;

  constructor(
    private following: boolean,
    private readonly leaveBottomThreshold = 24,
  ) {}

  isFollowing(): boolean {
    return this.following;
  }

  setFollowing(following: boolean): void {
    this.following = following;
    this.userScrolling = false;
  }

  beginUserScroll(): void {
    this.userScrolling = true;
  }

  endUserScroll(): void {
    this.userScrolling = false;
  }

  handleScroll(distanceFromBottom: number): boolean {
    if (
      !this.userScrolling
      || !this.following
      || distanceFromBottom <= this.leaveBottomThreshold
    ) {
      return false;
    }
    this.following = false;
    this.userScrolling = false;
    return true;
  }
}

export const selectRestorationAnchorId = (
  orderedIds: readonly number[],
  previousId: number,
): number | undefined => {
  if (orderedIds.length === 0) return undefined;
  const nextId = orderedIds.find((id) => id >= previousId);
  return nextId ?? orderedIds.at(-1);
};

export const resolveAnchoredScrollTop = (
  currentScrollTop: number,
  currentAnchorOffset: number,
  previousAnchorOffset: number,
): number => Math.max(
  0,
  currentScrollTop + currentAnchorOffset - previousAnchorOffset,
);
