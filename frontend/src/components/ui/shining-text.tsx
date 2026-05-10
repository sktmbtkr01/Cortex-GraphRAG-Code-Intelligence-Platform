"use client";

import * as React from "react";
import { motion } from "motion/react";

export function ShiningText({ text }: { text: string }) {
  return (
    <motion.span
      className="shining-text"
      initial={{ backgroundPosition: "200% 0" }}
      animate={{ backgroundPosition: "-200% 0" }}
      transition={{
        repeat: Infinity,
        duration: 2,
        ease: "linear",
      }}
    >
      {text}
    </motion.span>
  );
}
