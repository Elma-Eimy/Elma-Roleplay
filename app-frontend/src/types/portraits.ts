export interface CharacterPortrait {
  id: number;
  name: string;
  image_path: string;
}

export interface PortraitSelection {
  session_id: number;
  portrait_id: number | null;
  image_path: string;
  revision: string;
}
