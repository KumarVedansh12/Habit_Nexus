const searchInput =
document.getElementById("friendSearch");

if(searchInput){

    searchInput.addEventListener(
        "keyup",

        function(){

            const value =
            this.value.toLowerCase();

            const cards =
            document.querySelectorAll(
                ".discover-card"
            );

            cards.forEach(card=>{

                const text =
                card.innerText.toLowerCase();

                card.style.display =
                text.includes(value)
                ? "block"
                : "none";

            });

        }
    );
}
