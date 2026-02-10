from scr.scraper import IFTScraper
from rich import print

def main():
    print("[bold cyan]Scraper IFT – Numeración[/bold cyan]")
    scraper = IFTScraper("data/input/numeros.csv",
                         "data/output/resultados.csv",
                         headless=True)
    scraper.run()
    print("[green]Proceso terminado. Revisa data/output/resultados.csv[/]")

if __name__ == "__main__":
    main()