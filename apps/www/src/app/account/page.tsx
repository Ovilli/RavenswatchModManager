'use client';

import { ApiError } from '@rsmm/api-client';
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Spinner,
} from '@rsmm/ui';
import { useMutation } from '@tanstack/react-query';
import { AlertTriangle, ImageIcon, KeyRound, Loader2, Mail, Save, Trash2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { authClient, useSession } from '../../lib/auth-client';

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MiB`;
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { error?: string } | null;
    return body?.error ?? `HTTP ${err.status}`;
  }
  return err instanceof Error ? err.message : String(err);
}

export default function AccountPage() {
  const router = useRouter();
  const { data: session, isPending } = useSession();

  const [name, setName] = useState('');
  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  const [newEmail, setNewEmail] = useState('');
  const [emailMsg, setEmailMsg] = useState<string | null>(null);

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [pwMsg, setPwMsg] = useState<string | null>(null);

  useEffect(() => {
    if (session?.user) setName(session.user.name ?? '');
  }, [session]);

  const saveName = useMutation({
    mutationFn: async () => {
      const res = await authClient.updateUser({ name: name.trim() });
      if (res.error) throw new Error(res.error.message ?? 'update failed');
    },
    onSuccess: () => setSavedMsg('Name saved.'),
  });

  const uploadAvatar = useMutation({
    mutationFn: async () => {
      if (!avatarFile) throw new Error('no file picked');
      const presigned = await api.me.presignAvatar({
        contentType: avatarFile.type as 'image/png' | 'image/jpeg' | 'image/webp',
        sizeBytes: avatarFile.size,
      });
      const put = await fetch(presigned.uploadUrl, {
        method: 'PUT',
        body: avatarFile,
        headers: { 'Content-Type': avatarFile.type },
      });
      if (!put.ok) throw new Error(`avatar upload failed (${put.status})`);
      const upd = await authClient.updateUser({ image: presigned.publicUrl });
      if (upd.error) throw new Error(upd.error.message ?? 'image update failed');
    },
    onSuccess: () => {
      setAvatarFile(null);
      setSavedMsg('Profile picture updated.');
    },
  });

  const changeEmail = useMutation({
    mutationFn: async () => {
      setEmailMsg(null);
      const res = await authClient.changeEmail({
        newEmail: newEmail.trim(),
        // Absolute URL: the confirmation link is clicked from the email and
        // hits the API origin directly, so a relative path would resolve
        // against the API domain (404) instead of the website.
        callbackURL: `${window.location.origin}/account`,
      });
      if (res.error) throw new Error(res.error.message ?? 'email change failed');
    },
    onSuccess: () => {
      // better-auth only emails an approval link when the CURRENT address
      // is verified; for an unverified account the change applies
      // immediately and no email is sent. Tailor the message so we don't
      // tell unverified users to check an inbox that gets nothing.
      setEmailMsg(
        session?.user.emailVerified
          ? 'Check your current inbox for a link to confirm the change. Your email updates once you click it.'
          : 'Email updated.',
      );
      setNewEmail('');
    },
  });

  const changePassword = useMutation({
    mutationFn: async () => {
      setPwMsg(null);
      const res = await authClient.changePassword({
        currentPassword,
        newPassword,
        revokeOtherSessions: true,
      });
      if (res.error) throw new Error(res.error.message ?? 'password change failed');
    },
    onSuccess: () => {
      setPwMsg('Password updated. Other sessions were signed out.');
      setCurrentPassword('');
      setNewPassword('');
    },
  });

  const removeAccount = useMutation({
    mutationFn: async () => {
      const res = await authClient.deleteUser();
      if (res.error) throw new Error(res.error.message ?? 'delete failed');
    },
    onSuccess: () => {
      router.push('/');
    },
  });

  if (isPending) {
    return (
      <main className="container mx-auto px-6 py-16">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Checking session…
        </div>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="container mx-auto px-6 py-16">
        <div className="mx-auto max-w-md text-center">
          <h1 className="text-3xl font-bold tracking-tight">Sign in required</h1>
          <Link
            href={{ pathname: '/auth/signin' }}
            className="mt-6 inline-flex h-10 items-center justify-center rounded-md bg-primary px-6 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Sign in
          </Link>
        </div>
      </main>
    );
  }

  const user = session.user;

  return (
    <main className="container mx-auto max-w-2xl space-y-8 px-6 py-12">
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Account</h1>
        <p className="mt-1 text-sm text-muted-foreground">Manage your profile and account.</p>
      </header>

      <Card className="grimoire-card">
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>{user.email}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center gap-4">
            <div className="h-20 w-20 overflow-hidden rounded-full bg-muted">
              {user.image ? (
                <img src={user.image} alt="Current avatar" className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-2xl text-muted-foreground">
                  {(user.name?.[0] ?? user.email[0] ?? '?').toUpperCase()}
                </div>
              )}
            </div>
            <div className="flex-1 space-y-2">
              <label
                htmlFor="avatar"
                className="inline-flex items-center gap-2 text-sm font-medium"
              >
                <ImageIcon className="h-4 w-4" /> Profile picture
              </label>
              <input
                id="avatar"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(e) => setAvatarFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm text-muted-foreground file:mr-4 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-sm file:font-medium hover:file:bg-secondary/80"
              />
              {avatarFile ? (
                <p className="text-xs text-muted-foreground">
                  {avatarFile.name} — {fmtBytes(avatarFile.size)}
                </p>
              ) : null}
              <Button
                size="sm"
                onClick={() => uploadAvatar.mutate()}
                disabled={!avatarFile || uploadAvatar.isPending}
              >
                {uploadAvatar.isPending ? <Spinner /> : null} Upload picture
              </Button>
              {uploadAvatar.isError ? (
                <p className="text-xs text-destructive">{describeError(uploadAvatar.error)}</p>
              ) : null}
            </div>
          </div>

          <div className="space-y-2">
            <label htmlFor="name" className="text-sm font-medium">
              Display name
            </label>
            <div className="flex gap-2">
              <Input
                id="name"
                value={name}
                onChange={(e) => setName((e.target as HTMLInputElement).value)}
                maxLength={64}
              />
              <Button onClick={() => saveName.mutate()} disabled={saveName.isPending}>
                {saveName.isPending ? <Spinner /> : <Save className="h-4 w-4" />} Save
              </Button>
            </div>
            {saveName.isError ? (
              <p className="text-xs text-destructive">{describeError(saveName.error)}</p>
            ) : null}
          </div>

          {savedMsg ? <p className="text-xs text-muted-foreground">{savedMsg}</p> : null}
        </CardContent>
      </Card>

      <Card className="grimoire-card">
        <CardHeader>
          <CardTitle>Email</CardTitle>
          <CardDescription>
            Current: {user.email}
            {user.emailVerified ? null : ' (unverified)'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <label htmlFor="new-email" className="text-sm font-medium">
            New email
          </label>
          <div className="flex gap-2">
            <Input
              id="new-email"
              type="email"
              placeholder="new@email.com"
              value={newEmail}
              onChange={(e) => setNewEmail((e.target as HTMLInputElement).value)}
            />
            <Button
              onClick={() => changeEmail.mutate()}
              disabled={!newEmail.trim() || changeEmail.isPending}
            >
              {changeEmail.isPending ? <Spinner /> : <Mail className="h-4 w-4" />} Change
            </Button>
          </div>
          {changeEmail.isError ? (
            <p className="text-xs text-destructive">{describeError(changeEmail.error)}</p>
          ) : null}
          {emailMsg ? <p className="text-xs text-muted-foreground">{emailMsg}</p> : null}
        </CardContent>
      </Card>

      <Card className="grimoire-card">
        <CardHeader>
          <CardTitle>Password</CardTitle>
          <CardDescription>Set a new password. This signs out your other sessions.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input
            type="password"
            placeholder="current password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword((e.target as HTMLInputElement).value)}
            autoComplete="current-password"
          />
          <Input
            type="password"
            placeholder="new password (min 8 chars)"
            value={newPassword}
            onChange={(e) => setNewPassword((e.target as HTMLInputElement).value)}
            minLength={8}
            autoComplete="new-password"
          />
          <Button
            onClick={() => changePassword.mutate()}
            disabled={!currentPassword || newPassword.length < 8 || changePassword.isPending}
          >
            {changePassword.isPending ? <Spinner /> : <KeyRound className="h-4 w-4" />} Update
            password
          </Button>
          {changePassword.isError ? (
            <p className="text-xs text-destructive">{describeError(changePassword.error)}</p>
          ) : null}
          {pwMsg ? <p className="text-xs text-muted-foreground">{pwMsg}</p> : null}
        </CardContent>
      </Card>

      <Card className="grimoire-card border-destructive/30">
        <CardHeader>
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-1 h-4 w-4 text-destructive" />
            <div>
              <CardTitle>Delete account</CardTitle>
              <CardDescription>
                Removes your user row, all sessions, and disconnects any linked OAuth accounts. Mods
                you own become unowned — they stay published but can no longer be edited. This
                cannot be undone.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button
            variant="destructive"
            disabled={removeAccount.isPending}
            onClick={() => {
              if (
                window.confirm(
                  'Delete your account? This cannot be undone. Mods you published will stay live but become unowned.',
                )
              ) {
                removeAccount.mutate();
              }
            }}
          >
            {removeAccount.isPending ? <Spinner /> : <Trash2 className="h-4 w-4" />} Delete my
            account
          </Button>
          {removeAccount.isError ? (
            <p className="text-xs text-destructive">{describeError(removeAccount.error)}</p>
          ) : null}
        </CardContent>
      </Card>
    </main>
  );
}
