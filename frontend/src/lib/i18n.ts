import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'

import ptBR from '@/locales/pt-BR.json'
import en from '@/locales/en.json'
import es from '@/locales/es.json'
import pl from '@/locales/pl.json'
import it from '@/locales/it.json'

function syncHtmlLang(lng: string) {
  document.documentElement.lang = lng
}

// Read a previously persisted language choice (the key i18next-browser-
// languagedetector writes to when caches includes 'localStorage'). Returns
// undefined when the user has never chosen — letting the pt-BR default apply.
function storedLanguage(): string | undefined {
  try {
    return localStorage.getItem('i18nextLng') ?? undefined
  } catch {
    return undefined
  }
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      'pt-BR': { translation: ptBR },
      en: { translation: en },
      es: { translation: es },
      pl: { translation: pl },
      it: { translation: it },
    },
    fallbackLng: 'en',
    // Portuguese (pt-BR) is this fork's default. Honour an explicit, persisted
    // choice (querystring/localStorage/cookie) but do NOT auto-pick the browser
    // language — so a user who picked English keeps it. When nothing is stored,
    // the detector returns no language and i18next applies `lng` below.
    lng: storedLanguage() ?? 'pt-BR',
    detection: {
      order: ['querystring', 'localStorage', 'cookie'],
      caches: ['localStorage'],
    },
    interpolation: {
      escapeValue: false,
    },
  })

syncHtmlLang(i18n.language)
i18n.on('languageChanged', syncHtmlLang)

export type SupportedLang = 'pt-BR' | 'en' | 'es' | 'pl' | 'it'

// Normalise any browser/i18n language tag to one of our supported keys. The
// backend and resource bundles key Portuguese as the region-tagged 'pt-BR'
// while 'en'/'es' are bare, so naively truncating to the primary subtag
// (e.g. 'pt-BR'.split('-')[0] -> 'pt') yields a value neither side recognises
// and silently falls back to English. Match on the primary subtag instead.
export function resolveSupportedLang(lng?: string | null): SupportedLang {
  const tag = (lng ?? '').toLowerCase()
  if (tag.startsWith('pt')) return 'pt-BR'
  if (tag.startsWith('es')) return 'es'
  if (tag.startsWith('pl')) return 'pl'
  if (tag.startsWith('it')) return 'it'
  return 'en'
}

export default i18n
