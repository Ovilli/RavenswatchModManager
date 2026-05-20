import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from '@rsmm/ui';
import Link from 'next/link';

export default function Home() {
  return (
    <main className="container mx-auto px-6 py-16">
      <section className="space-y-4 text-center">
        <h1 className="text-5xl font-extrabold tracking-tight">Ravenswatch Mod Manager</h1>
        <p className="mx-auto max-w-2xl text-lg text-muted-foreground">
          One toolkit. Browser. Windows. macOS. Linux. Browse community mods, install in one
          click, and ship your own to the registry.
        </p>
        <div className="flex justify-center gap-3 pt-4">
          <Link href="/registry">
            <Button size="lg">Browse registry</Button>
          </Link>
          <Link href="/download">
            <Button size="lg" variant="outline">
              Download client
            </Button>
          </Link>
          <a
            href="https://github.com/Ovilli/RavenswatchModManager"
            target="_blank"
            rel="noopener noreferrer"
          >
            <Button size="lg" variant="outline">GitHub</Button>
          </a>
        </div>
      </section>

      <section className="mt-24 grid grid-cols-1 gap-6 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Cooked asset overrides</CardTitle>
            <CardDescription>Swap textures, audio, meshes — anything cooked.</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Drop assets into a mod folder and `rsmm apply` installs them with full rollback.
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Lua scripting</CardTitle>
            <CardDescription>winhttp.dll proxy + scripting API.</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Author behaviour in Lua. Call any of 53k game functions via `rsmm.call`.
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Conflict-free merging</CardTitle>
            <CardDescription>Field-level merges via manifest.toml.</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Multiple mods can patch the same file without overwriting each other.
          </CardContent>
        </Card>
      </section>
    </main>
  );
}
