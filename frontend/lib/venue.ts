"use client";

import { createContext, useContext } from "react";

/** Which of a person's two accounts the Trading page is showing. Paper unless a page says otherwise. */
export type Venue = "paper" | "live";
export const VenueContext = createContext<Venue>("paper");
export const useVenue = () => useContext(VenueContext);
