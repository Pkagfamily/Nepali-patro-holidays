#!/bin/bash
# Commit the given files and push, retrying if another job saved at the same time.
git add "$@"
if git diff --cached --quiet; then echo "nothing to save"; exit 0; fi
git -c user.name=holiday-robot -c user.email=robot@users.noreply.github.com commit -qm "Robot: update $*"
for i in 1 2 3 4 5 6; do
  if git push -q; then echo "saved"; exit 0; fi
  echo "push failed (attempt $i) – someone else saved; merging and retrying"
  sleep $((i * 7))
  git pull -q --rebase || { git rebase --abort; git pull -q --no-rebase -X ours; }
done
echo "could not save after 6 attempts"; exit 1
