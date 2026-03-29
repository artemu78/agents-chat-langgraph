import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider, type Auth } from "firebase/auth";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

/**
 * In Vite dev, Firebase is not initialized by default so missing/invalid
 * VITE_FIREBASE_* does not throw auth/invalid-api-key at import time.
 * Set VITE_USE_FIREBASE_IN_DEV=true to initialize Firebase while using `vite`.
 */
export const devFirebaseDisabled =
  import.meta.env.DEV && import.meta.env.VITE_USE_FIREBASE_IN_DEV !== "true";

let authInstance: Auth | undefined;

if (!devFirebaseDisabled) {
  const app = initializeApp(firebaseConfig);
  authInstance = getAuth(app);
}

export const auth = authInstance;
export const googleProvider = new GoogleAuthProvider();
