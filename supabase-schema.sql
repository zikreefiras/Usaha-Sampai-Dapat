create table if not exists public.game_progress (
  user_id uuid primary key references auth.users (id) on delete cascade,
  money numeric not null default 0 check (money >= 0 and money <= 1000000000000000000),
  level integer not null default 0 check (level >= 0 and level <= 1000000),
  device text not null default '2' check (device in ('1', '2')),
  updated_at timestamptz not null default now()
);

alter table public.game_progress enable row level security;

drop policy if exists "Users can read their own game progress" on public.game_progress;
create policy "Users can read their own game progress"
  on public.game_progress for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "Users can create their own game progress" on public.game_progress;
create policy "Users can create their own game progress"
  on public.game_progress for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

drop policy if exists "Users can update their own game progress" on public.game_progress;
create policy "Users can update their own game progress"
  on public.game_progress for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

grant select, insert, update on public.game_progress to authenticated;
