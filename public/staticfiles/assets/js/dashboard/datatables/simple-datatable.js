window.addEventListener('DOMContentLoaded', event => {
    const tableIds = ['offers_table', 'assets_table', 'locations_table', 'asset_and_category_table', 'offers_table', 'categories_table', 'assetinline_table'];
    tableIds.forEach(id => {
        const table = document.getElementById(id);
        if (table) {
            new simpleDatatables.DataTable(table, {
                perPage: 5,
                perPageSelect: [5, 10, 25, 50]
            });
        }
    });
});