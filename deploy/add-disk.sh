#!/usr/bin/env bash
# Puts the app's videos on the extra (empty) disk added in the Timeweb panel.
#   bash /opt/relax-factory/deploy/add-disk.sh
# Only an empty disk with no partitions and no file system is formatted. The
# videos already on the server are copied onto it. n8n is not touched.
set -euo pipefail
DATA=/var/lib/relax-factory

if mountpoint -q "$DATA"; then
  echo "Видео уже на отдельном диске:"; df -h "$DATA"; exit 0
fi
if [ -f "$DATA/busy" ]; then
  echo "Сейчас идёт рендер. Запустите, когда он закончится."; exit 1
fi

EMPTY=()
for d in $(lsblk -dnpo NAME,TYPE | awk '$2=="disk"{print $1}'); do
  [ "$(lsblk -nro NAME "$d" | wc -l)" -eq 1 ] || continue          # has partitions
  [ -z "$(blkid -o value -s TYPE "$d" 2>/dev/null || true)" ] || continue  # has a file system
  EMPTY+=("$d")
done
if [ "${#EMPTY[@]}" -ne 1 ]; then
  echo "Пустых дисков найдено: ${#EMPTY[@]}, нужен ровно один. Ничего не менял."
  lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT
  exit 1
fi
DISK=${EMPTY[0]}
echo "Новый пустой диск: $DISK, размер $(lsblk -dno SIZE "$DISK")"
read -r -p "Отформатировать его под видео? Напишите да: " ok
[ "$ok" = "да" ] || { echo "Отменено, ничего не менял."; exit 1; }

mkfs.ext4 -q -L relax-videos "$DISK"
UUID=$(blkid -o value -s UUID "$DISK")
mkdir -p /mnt/relax-new
mount "$DISK" /mnt/relax-new

echo "Останавливаю приложение и копирую видео на новый диск…"
docker stop relax-factory >/dev/null 2>&1 || true
mkdir -p "$DATA"
cp -a "$DATA/." /mnt/relax-new/
umount /mnt/relax-new && rmdir /mnt/relax-new
mv "$DATA" "$DATA.old" && mkdir -p "$DATA"
echo "UUID=$UUID $DATA ext4 defaults,nofail 0 2" >> /etc/fstab
mount "$DATA"
rm -rf "$DATA.old"
docker start relax-factory >/dev/null
echo
echo "Готово. Видео теперь на новом диске:"
df -h "$DATA"
