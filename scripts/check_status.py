from headless_ariadne import HeadlessAriadne

def check_statuses():
    a = HeadlessAriadne()
    tickets = a.list_tickets()
    for t in tickets:
        num = int(t['number'])
        if 15 <= num <= 20:
            print(f"#{t['number']} - {t['title']} - Status: {t.get('state', 'Unknown')}")

if __name__ == "__main__":
    check_statuses()
