// The film page: the player (player.ts), its chapters, transcript and notes
// below it, and the page's own visit count. The player's first tap plays the
// film and, on a phone, takes it full screen and landscape.
import "./player";
import { sendEvent } from "./telemetry";

sendEvent("page_view");
