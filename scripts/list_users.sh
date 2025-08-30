REDIS_URL=redis://red-d2h4n78gjchc73bqndsg:6379
USERS=$(redis-cli -u $REDIS_URL --scan --pattern "user:*" | sort)
NUM_USERS=$(redis-cli -u $REDIS_URL --scan --pattern "user:*" | wc -l)
echo "List of $NUM_USERS users in the database:"
echo $USERS