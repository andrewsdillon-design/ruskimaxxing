// The website's "Return to the app" button opens ruskimaxxing://signed-in. The sign-in watcher (state/app)
// finishes the sign-in on its own; this just lands on Setup, where the cloud backup status shows.
import { Redirect } from 'expo-router';

export default function SignedIn() {
  return <Redirect href="/settings" />;
}
