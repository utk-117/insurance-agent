# usage: cols.sh <id> <first> <last>  -> re-extract pages as left column then right column
id=$1; for p in $(seq $2 $3); do
  read W H < <(pdfinfo -f $p -l $p pdf/$id.pdf | awk '/^Page.*size/{print int($4), int($6)}')
  half=$((W/2))
  { pdftotext -r 72 -f $p -l $p -x 0 -y 0 -W $half -H $H pdf/$id.pdf - ; pdftotext -r 72 -f $p -l $p -x $half -y 0 -W $half -H $H pdf/$id.pdf - ; } 2>/dev/null | sed 's/[ \t]\+/ /g' | sed '/^\s*$/d' > pages/$id/$(printf %02d $p).txt
done
: > full_$id.txt; for f in pages/$id/*.txt; do echo "<<<PAGE $((10#$(basename $f .txt)))>>>" >> full_$id.txt; cat $f >> full_$id.txt; done
