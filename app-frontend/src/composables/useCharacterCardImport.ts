import { ref } from "vue";
import { parseCharacter } from "@/api/characters";
import type {
  ParsedCharacterData,
  ParseCharacterResponse,
} from "@/api/characters";
import { cardImportError } from "@/utils/characterCard";

export function useCharacterCardImport(
  parse: (file: string) => Promise<ParseCharacterResponse> = parseCharacter,
) {
  const card = ref<ParsedCharacterData | null>(null);
  const loading = ref(false);
  const error = ref("");
  let generation = 0;
  const reset = () => {
    generation++;
    card.value = null;
    error.value = "";
    loading.value = false;
  };
  const load = async (file: string) => {
    const request = ++generation;
    loading.value = true;
    error.value = "";
    card.value = null;
    try {
      const result = await parse(file);
      if (request === generation) card.value = result.data;
    } catch (failure) {
      if (request === generation) error.value = cardImportError(failure);
    } finally {
      if (request === generation) loading.value = false;
    }
  };
  return { card, loading, error, reset, load };
}
