"use client";

import { useEffect, useState } from "react";
import { animate } from "framer-motion";

type Props = {
  value: number;
  decimals?: number;
  suffix?: string;
  duration?: number;
};

export function AnimatedNumber({ value, decimals = 0, suffix = "", duration = 0.9 }: Props) {
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    const controls = animate(display, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate(latest) {
        setDisplay(latest);
      },
    });
    return () => controls.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <span className="tabular-nums">
      {display.toFixed(decimals)}
      {suffix}
    </span>
  );
}
