"use client";

import { useEffect, useState } from "react";

import { currentRole, type DemoRole } from "@/lib/api";

/** Current demo role; re-renders when the top-bar switcher changes it. */
export function useRole(): DemoRole {
  const [role, setRoleState] = useState<DemoRole>("bid_manager");
  useEffect(() => {
    const sync = () => setRoleState(currentRole());
    sync();
    window.addEventListener("tb-role-change", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("tb-role-change", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  return role;
}
