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
import { AlertTriangle, KeyRound, Loader2, Mail, Save, Trash2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { authClient, useSession } from '../../lib/auth-client';
import { putFile } from '../../lib/upload';
import { FileDrop } from '../components/file-drop';
import { ApiTokensPanel } from './api-tokens-panel';
import { PrivacyPanel } from './privacy-panel';

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { error?: string } | null;
    return body?.error ?? `HTTP ${err.status}`;
  }
  return err instanceof Error ? err.message : String(err);
}

const ACCOUNT_SECTIONS = [
  { id: 'profile', label: 'Profile' },
  { id: 'email', label: 'Email' },
  { id: 'privacy', label: 'Privacy' },
  { id: 'tokens', label: 'API tokens' },
  { id: 'password', label: 'Password' },
  { id: 'delete', label: 'Delete account' },
] as const;

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

  // Show the picked picture in the avatar circle before it is uploaded.
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  useEffect(() => {
    if (!avatarFile) {
      setAvatarPreview(null);
      return;
    }
    const url = URL.createObjectURL(avatarFile);
    setAvatarPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [avatarFile]);

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
      await putFile(presigned.uploadUrl, avatarFile, {
        headers: { 'Content-Type': avatarFile.type },
        what: 'avatar upload',
      });
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
        <h1 className="font-display text-5xl text-parchment">Account</h1>
        <p className="mt-1 text-sm text-muted-foreground">Manage your profile and account.</p>
        <nav aria-label="Account sections" className="mt-4 flex flex-wrap gap-2">
          {ACCOUNT_SECTIONS.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition hover:border-gilt/60 hover:text-foreground"
            >
              {s.label}
            </a>
          ))}
        </nav>
      </header>

      <Card id="profile" className="grimoire-card scroll-mt-24">
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>{user.email}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center gap-4">
            <div className="h-20 w-20 shrink-0 overflow-hidden rounded-full bg-muted">
              {avatarPreview || user.image ? (
                <img
                  src={avatarPreview ?? user.image ?? ''}
                  alt={avatarPreview ? 'New avatar preview' : 'Current avatar'}
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-2xl text-muted-foreground">
                  {(user.name?.[0] ?? user.email[0] ?? '?').toUpperCase()}
                </div>
              )}
            </div>
            <div className="min-w-0 flex-1 space-y-2">
              <FileDrop
                id="avatar"
                accept="image/png,image/jpeg,image/webp"
                label="Profile picture"
                hint="PNG, JPEG or WebP"
                file={avatarFile}
                onFile={(f) => {
                  setSavedMsg(null);
                  setAvatarFile(f);
                }}
                disabled={uploadAvatar.isPending}
              />
              {avatarFile ? (
                <Button
                  size="sm"
                  onClick={() => uploadAvatar.mutate()}
                  disabled={uploadAvatar.isPending}
                >
                  {uploadAvatar.isPending ? <Spinner /> : null} Save picture
                </Button>
              ) : null}
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
              <Button
                onClick={() => saveName.mutate()}
                disabled={
                  saveName.isPending || !name.trim() || name.trim() === (user.name ?? '').trim()
                }
              >
                {saveName.isPending ? <Spinner /> : <Save className="h-4 w-4" />} Save
              </Button>
            </div>
            {saveName.isError ? (
              <p className="text-xs text-destructive">{describeError(saveName.error)}</p>
            ) : null}
          </div>

          {savedMsg ? <output className="block text-xs text-moss">✓ {savedMsg}</output> : null}
        </CardContent>
      </Card>

      <Card id="email" className="grimoire-card scroll-mt-24">
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

      <div id="privacy" className="scroll-mt-24">
        <PrivacyPanel />
      </div>

      <div id="tokens" className="scroll-mt-24">
        <ApiTokensPanel />
      </div>

      <Card id="password" className="grimoire-card scroll-mt-24">
        <CardHeader>
          <CardTitle>Password</CardTitle>
          <CardDescription>Set a new password. This signs out your other sessions.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1.5">
            <label htmlFor="current-password" className="text-sm font-medium">
              Current password
            </label>
            <Input
              id="current-password"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword((e.target as HTMLInputElement).value)}
              autoComplete="current-password"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="new-password" className="text-sm font-medium">
              New password
            </label>
            <Input
              id="new-password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword((e.target as HTMLInputElement).value)}
              minLength={8}
              autoComplete="new-password"
              aria-describedby="new-password-hint"
            />
            <p
              id="new-password-hint"
              className={`text-xs ${newPassword.length > 0 && newPassword.length < 8 ? 'text-destructive' : 'text-muted-foreground'}`}
            >
              At least 8 characters
              {newPassword.length > 0 && newPassword.length < 8
                ? ` (${8 - newPassword.length} more)`
                : ''}
              .
            </p>
          </div>
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

      <Card id="delete" className="grimoire-card scroll-mt-24 border-destructive/30">
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
